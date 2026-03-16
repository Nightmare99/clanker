"""GitHub Copilot authentication using device code flow."""

import json
import os
import time
from pathlib import Path

import requests

from clanker.logging import get_logger

logger = get_logger("auth.github_copilot")

# GitHub OAuth client ID for Copilot
GITHUB_CLIENT_ID = "Iv1.b507a08c87ecfe98"

# Token storage path
GITHUB_TOKEN_PATH = Path.home() / ".clanker" / "github_token.json"

# Common headers for GitHub API requests
GITHUB_HEADERS = {
    "accept": "application/json",
    "editor-version": "Neovim/0.6.1",
    "editor-plugin-version": "copilot.vim/1.16.0",
    "content-type": "application/json",
    "user-agent": "GithubCopilot/1.155.0",
    "accept-encoding": "gzip,deflate,br",
}


def authenticate_github_copilot(console=None) -> str | None:
    """Authenticate with GitHub Copilot using device code flow.

    This initiates the OAuth device flow, prompting the user to visit
    a URL and enter a code to authenticate.

    Args:
        console: Optional console instance for output.

    Returns:
        The access token if successful, None otherwise.
    """
    logger.info("Starting GitHub Copilot authentication")

    # Request device code
    try:
        resp = requests.post(
            "https://github.com/login/device/code",
            headers=GITHUB_HEADERS,
            json={"client_id": GITHUB_CLIENT_ID, "scope": "read:user"},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("Failed to request device code: %s", e)
        if console:
            console.print_error(f"Failed to connect to GitHub: {e}")
        return None

    resp_json = resp.json()
    device_code = resp_json.get("device_code")
    user_code = resp_json.get("user_code")
    verification_uri = resp_json.get("verification_uri")
    expires_in = resp_json.get("expires_in", 900)
    interval = resp_json.get("interval", 5)

    if not device_code or not user_code:
        logger.error("Invalid device code response: %s", resp_json)
        if console:
            console.print_error("Failed to get device code from GitHub")
        return None

    # Display instructions to user
    msg = f"""
[bold cyan]*BZZZT*[/bold cyan] GitHub Copilot Authentication Required

[bold]1.[/bold] Visit: [cyan]{verification_uri}[/cyan]
[bold]2.[/bold] Enter code: [bold yellow]{user_code}[/bold yellow]

[dim]Waiting for authentication... (expires in {expires_in // 60} minutes)[/dim]
"""
    if console:
        console.print(msg)
    else:
        print(f"\nVisit: {verification_uri}")
        print(f"Enter code: {user_code}")
        print(f"\nWaiting for authentication... (expires in {expires_in // 60} minutes)")

    # Poll for access token
    start_time = time.time()
    access_token = None

    while time.time() - start_time < expires_in:
        time.sleep(interval)

        try:
            resp = requests.post(
                "https://github.com/login/oauth/access_token",
                headers=GITHUB_HEADERS,
                json={
                    "client_id": GITHUB_CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning("Token poll request failed: %s", e)
            continue

        resp_json = resp.json()
        error = resp_json.get("error")

        if error == "authorization_pending":
            # User hasn't authorized yet, keep polling
            continue
        elif error == "slow_down":
            # We're polling too fast, increase interval
            interval += 5
            continue
        elif error == "expired_token":
            logger.error("Device code expired")
            if console:
                console.print_error("Authentication timed out. Please try again.")
            return None
        elif error == "access_denied":
            logger.error("User denied access")
            if console:
                console.print_error("Authentication was denied.")
            return None
        elif error:
            logger.error("Authentication error: %s", error)
            if console:
                console.print_error(f"Authentication error: {error}")
            return None

        access_token = resp_json.get("access_token")
        if access_token:
            break

    if not access_token:
        logger.error("Authentication timed out")
        if console:
            console.print_error("Authentication timed out. Please try again.")
        return None

    # Exchange GitHub token for Copilot token
    copilot_token = _get_copilot_token(access_token)
    if not copilot_token:
        logger.error("Failed to get Copilot token")
        if console:
            console.print_error("Failed to get Copilot API access. Ensure you have an active Copilot subscription.")
        return None

    # Save both tokens
    _save_token(access_token, copilot_token)

    logger.info("GitHub Copilot authentication successful")
    if console:
        console.print("[bold green]Authentication successful![/bold green] [bold cyan]*CLANK*[/bold cyan]")

    return copilot_token


def _get_copilot_token(github_token: str) -> str | None:
    """Exchange GitHub OAuth token for Copilot API token.

    Args:
        github_token: The GitHub OAuth access token.

    Returns:
        The Copilot API token if successful, None otherwise.
    """
    headers = {
        **GITHUB_HEADERS,
        "authorization": f"token {github_token}",
    }

    try:
        resp = requests.get(
            "https://api.github.com/copilot_internal/v2/token",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("Failed to get Copilot token: %s", e)
        return None

    resp_json = resp.json()
    copilot_token = resp_json.get("token")

    if not copilot_token:
        logger.error("No token in Copilot response: %s", resp_json)
        return None

    return copilot_token


def _save_token(github_token: str, copilot_token: str) -> None:
    """Save tokens to file and environment."""
    GITHUB_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)

    token_data = {
        "github_token": github_token,
        "copilot_token": copilot_token,
        "created_at": time.time(),
    }

    with open(GITHUB_TOKEN_PATH, "w") as f:
        json.dump(token_data, f)

    # Set Copilot token in environment (this is what the API uses)
    os.environ["GITHUB_TOKEN"] = copilot_token

    logger.debug("Tokens saved to %s", GITHUB_TOKEN_PATH)


def get_github_token() -> str | None:
    """Get the Copilot API token from environment or stored file.

    Returns:
        The Copilot API token if available, None otherwise.
    """
    # First check environment
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token

    # Then check stored file
    if GITHUB_TOKEN_PATH.exists():
        try:
            with open(GITHUB_TOKEN_PATH) as f:
                data = json.load(f)
                # Prefer copilot_token (new format), fall back to access_token (old format)
                token = data.get("copilot_token") or data.get("access_token")
                if token:
                    # Set in environment for this session
                    os.environ["GITHUB_TOKEN"] = token
                    return token
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read stored token: %s", e)

    return None


def is_github_token_valid() -> bool:
    """Check if we have a valid GitHub token.

    Note: The token may still be expired (tokens last ~8 hours),
    but this checks if one exists.

    Returns:
        True if a token is available.
    """
    return get_github_token() is not None


def clear_github_token() -> None:
    """Clear the stored GitHub token."""
    if GITHUB_TOKEN_PATH.exists():
        GITHUB_TOKEN_PATH.unlink()

    if "GITHUB_TOKEN" in os.environ:
        del os.environ["GITHUB_TOKEN"]

    logger.info("GitHub token cleared")


def get_available_copilot_models() -> list[str]:
    """Get list of available models from GitHub Copilot API.

    Returns:
        List of model names available for the current user.
    """
    token = get_github_token()
    if not token:
        return []

    # Use headers that the Copilot API accepts
    headers = {
        "authorization": f"Bearer {token}",
        "editor-version": "vscode/1.85.0",
        "editor-plugin-version": "copilot/1.155.0",
        "user-agent": "GitHubCopilotChat/0.12.0",
        "accept": "application/json",
    }

    try:
        resp = requests.get(
            "https://api.githubcopilot.com/models",
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        # Extract model IDs from response (format: {"data": [{"id": "model-name", ...}]})
        models = []
        for model in data.get("data", []):
            model_id = model.get("id")
            # Filter out embedding models - we only want chat models
            if model_id and "embedding" not in model_id.lower():
                models.append(model_id)

        return sorted(set(models))  # Remove duplicates
    except requests.RequestException as e:
        logger.debug("Failed to fetch Copilot models: %s", e)
        return []
    except (KeyError, TypeError) as e:
        logger.debug("Failed to parse Copilot models response: %s", e)
        return []
