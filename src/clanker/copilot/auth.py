"""Copilot authentication and token management."""

from __future__ import annotations

import json
import ssl
import time
from pathlib import Path

from clanker.logging import get_logger

logger = get_logger("copilot.auth")


def _get_ssl_context() -> ssl.SSLContext:
    """Get SSL context with proper certificate bundle.

    Uses certifi's CA bundle for packaged binaries where system certs
    may not be accessible.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        # Fall back to default context if certifi not available
        return ssl.create_default_context()


def _get_copilot_token_path() -> Path:
    """Get path to stored Copilot token."""
    return Path.home() / ".clanker" / "copilot_token"


def get_github_token() -> str | None:
    """Get GitHub token from environment variables.

    Checks in order: COPILOT_TOKEN, COPILOT_GITHUB_TOKEN, GH_TOKEN, GITHUB_TOKEN
    """
    import os

    for var in ["COPILOT_TOKEN", "COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"]:
        token = os.environ.get(var)
        if token:
            logger.debug("Using token from %s", var)
            return token

    return None


def load_copilot_token() -> str | None:
    """Load stored Copilot token if valid and not expired."""
    token_path = _get_copilot_token_path()
    if not token_path.exists():
        return None

    try:
        data = json.loads(token_path.read_text())
        # Check if token is expired (tokens last ~8 hours, we refresh at 7)
        if data.get("expires_at", 0) > time.time():
            return data.get("access_token")
        else:
            logger.debug("Stored Copilot token expired")
    except Exception as e:
        logger.debug("Failed to load stored token: %s", e)

    return None


def save_copilot_token(access_token: str, expires_in: int = 28800) -> None:
    """Save Copilot token for reuse.

    Args:
        access_token: The OAuth access token.
        expires_in: Token lifetime in seconds (default 8 hours).
    """
    token_path = _get_copilot_token_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "access_token": access_token,
        "expires_at": time.time() + expires_in - 3600,  # Refresh 1 hour early
    }
    token_path.write_text(json.dumps(data))
    logger.debug("Saved Copilot token to %s", token_path)


def authenticate_copilot_sync() -> str:
    """Authenticate with GitHub Copilot using device flow.

    Performs OAuth device flow authentication:
    1. Requests a device code from GitHub
    2. Prompts user to visit URL and enter code
    3. Polls for access token

    Returns:
        The access token.

    Raises:
        RuntimeError: If authentication fails.
    """
    import urllib.request

    # Copilot client ID (same as used by copilot.vim)
    CLIENT_ID = "Iv1.b507a08c87ecfe98"

    headers = {
        "Accept": "application/json",
        "Editor-Version": "Neovim/0.9.0",
        "Editor-Plugin-Version": "copilot.vim/1.16.0",
        "Content-Type": "application/json",
        "User-Agent": "GithubCopilot/1.155.0",
    }

    # Get SSL context for HTTPS requests
    ssl_context = _get_ssl_context()

    # Step 1: Request device code
    req = urllib.request.Request(
        "https://github.com/login/device/code",
        data=json.dumps({"client_id": CLIENT_ID, "scope": "read:user"}).encode(),
        headers=headers,
        method="POST",
    )

    with urllib.request.urlopen(req, context=ssl_context) as resp:
        data = json.loads(resp.read().decode())

    device_code = data["device_code"]
    user_code = data["user_code"]
    verification_uri = data["verification_uri"]
    interval = data.get("interval", 5)

    print(f"\n  To authenticate with GitHub Copilot:")
    print(f"  1. Visit: {verification_uri}")
    print(f"  2. Enter code: {user_code}")
    print(f"\n  Waiting for authentication...")

    # Step 2: Poll for access token
    while True:
        time.sleep(interval)

        req = urllib.request.Request(
            "https://github.com/login/oauth/access_token",
            data=json.dumps({
                "client_id": CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            }).encode(),
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, context=ssl_context) as resp:
            data = json.loads(resp.read().decode())

        if "access_token" in data:
            access_token = data["access_token"]
            save_copilot_token(access_token)
            print("  Authentication successful!\n")
            return access_token

        error = data.get("error")
        if error == "authorization_pending":
            continue
        elif error == "slow_down":
            interval += 5
        elif error == "expired_token":
            raise RuntimeError("Device code expired. Please try again.")
        elif error == "access_denied":
            raise RuntimeError("Access denied. Please try again.")
        else:
            raise RuntimeError(f"Authentication failed: {error}")


# Aliases for backward compatibility
_get_github_token = get_github_token
_load_copilot_token = load_copilot_token
_save_copilot_token = save_copilot_token
