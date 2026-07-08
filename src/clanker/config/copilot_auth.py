"""Native GitHub Copilot authentication and model discovery.

Lets a user connect their existing GitHub Copilot subscription as a model
provider without any external proxy process. This mirrors the device-code
login flow used by the official VS Code Copilot Chat extension:

1. GitHub OAuth **device code** flow (RFC 8628) obtains a GitHub token scoped
   to ``read:user`` -- the same public client id the VS Code extension uses.
2. That GitHub token is exchanged for a short-lived **Copilot bearer token**
   via GitHub's (undocumented) internal token endpoint.
3. The Copilot token, plus a handful of editor-identity headers that Copilot's
   backend uses to gate access, authorize calls to Copilot's own
   OpenAI-compatible chat-completions API -- consumed directly by
   ``langchain_openai.ChatOpenAI`` (base_url + default_headers), no separate
   proxy process required.
4. Copilot's own ``/models`` endpoint reports each model's real context
   window and output-token limits, used to auto-populate one ``ModelConfig``
   entry per model (named ``copilot:<model-id>``) with accurate
   ``max_input_tokens``/``max_tokens`` -- unlike a flat guess, this keeps the
   context-window display and summarization trigger correct.

Caveat: this talks to an undocumented GitHub endpoint and sends editor-identity
headers that identify the request as coming from VS Code's Copilot Chat
extension. This is the same mechanism third-party "Copilot bridge" tools use;
it is not an officially supported integration path.
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clanker.logging import get_logger

logger = get_logger("config.copilot_auth")

# The public client id the VS Code Copilot Chat extension registers with
# GitHub for its device-code OAuth flow.
GITHUB_CLIENT_ID = "Iv1.b507a08c87ecfe98"
GITHUB_APP_SCOPE = "read:user"

GITHUB_BASE_URL = "https://github.com"
GITHUB_API_BASE_URL = "https://api.github.com"

# Copilot Chat extension identity. Copilot's backend gates access to its
# OpenAI-compatible API on these headers, not just the bearer token.
COPILOT_VERSION = "0.26.7"
EDITOR_VERSION = "vscode/1.99.3"
EDITOR_PLUGIN_VERSION = f"copilot-chat/{COPILOT_VERSION}"
USER_AGENT = f"GitHubCopilotChat/{COPILOT_VERSION}"
GITHUB_API_VERSION = "2025-04-01"

COPILOT_BASE_URL = "https://api.githubcopilot.com"

# Where the GitHub + Copilot tokens are cached. Distinct from models.json's
# plaintext api_key convention -- a bearer token warrants tighter permissions.
COPILOT_TOKEN_PATH = Path.home() / ".clanker" / "copilot_auth.json"

# Refresh this many seconds before the token's reported expiry, so a request
# in flight doesn't race a token that just expired.
_REFRESH_SKEW_SECONDS = 60


class CopilotAuthError(Exception):
    """Raised when Copilot authentication is missing, expired, or fails."""


@dataclass
class DeviceFlowSession:
    """State for an in-progress GitHub device-code login."""

    device_code: str
    user_code: str
    verification_uri: str
    interval: int
    expires_at: float


def _get_ssl_context() -> ssl.SSLContext:
    """Build an SSL context backed by certifi's CA bundle.

    PyInstaller-frozen binaries have no system CA store, so the default
    context can't verify certificates. Using certifi's bundle explicitly
    fixes verification regardless of environment. (Duplicated in a couple of
    places in clanker -- e.g. ``tools/web_tools.py`` -- rather than imported,
    to avoid a config -> tools -> config import cycle: ``tools`` already
    imports from ``config``.)
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = 15,
) -> tuple[int, Any]:
    """POST/GET JSON over HTTPS, returning (status_code, parsed_body_or_None).

    Never raises on HTTP error status codes -- callers decide how to react to
    4xx/5xx (the device-code poll loop treats "pending" as a normal 4xx).
    """
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)

    context = _get_ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            raw = resp.read()
            parsed = json.loads(raw) if raw else None
            return resp.status, parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = None
        return exc.code, parsed
    except urllib.error.URLError as exc:
        raise CopilotAuthError(f"Network error contacting {url}: {exc.reason}") from exc


def _github_headers() -> dict[str, str]:
    return {
        "Editor-Version": EDITOR_VERSION,
        "Editor-Plugin-Version": EDITOR_PLUGIN_VERSION,
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }


def copilot_request_headers() -> dict[str, str]:
    """Editor-identity headers required on every Copilot chat-completions call.

    Does NOT include ``Authorization`` -- callers (``create_llm_from_config``)
    supply the bearer token separately via ``ChatOpenAI(api_key=...)``.
    """
    return {
        "Copilot-Integration-Id": "vscode-chat",
        "Editor-Version": EDITOR_VERSION,
        "Editor-Plugin-Version": EDITOR_PLUGIN_VERSION,
        "User-Agent": USER_AGENT,
        "Openai-Intent": "conversation-panel",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }


# ---------------------------------------------------------------------------
# Token cache
# ---------------------------------------------------------------------------

def _load_token_cache() -> dict[str, Any]:
    if not COPILOT_TOKEN_PATH.exists():
        return {}
    try:
        return json.loads(COPILOT_TOKEN_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read Copilot token cache: %s", exc)
        return {}


def _save_token_cache(data: dict[str, Any]) -> None:
    COPILOT_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    COPILOT_TOKEN_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(COPILOT_TOKEN_PATH, 0o600)
    except OSError as exc:  # pragma: no cover - platform-dependent (e.g. Windows)
        logger.warning("Could not chmod Copilot token cache: %s", exc)


def is_connected() -> bool:
    """Return True if a GitHub token has been cached (login has run)."""
    return bool(_load_token_cache().get("github_token"))


def disconnect() -> None:
    """Forget the cached GitHub/Copilot tokens (does not remove synced models)."""
    if COPILOT_TOKEN_PATH.exists():
        COPILOT_TOKEN_PATH.unlink()


# ---------------------------------------------------------------------------
# Device-code login flow
# ---------------------------------------------------------------------------

def start_device_flow() -> DeviceFlowSession:
    """Begin a GitHub device-code login. Returns the code to show the user."""
    status, payload = _http_json(
        f"{GITHUB_BASE_URL}/login/device/code",
        method="POST",
        headers=_github_headers(),
        body={"client_id": GITHUB_CLIENT_ID, "scope": GITHUB_APP_SCOPE},
    )
    if status != 200 or not payload:
        raise CopilotAuthError(f"Failed to start GitHub device login (HTTP {status})")

    now = time.time()
    return DeviceFlowSession(
        device_code=payload["device_code"],
        user_code=payload["user_code"],
        verification_uri=payload["verification_uri"],
        interval=int(payload.get("interval", 5)),
        expires_at=now + int(payload.get("expires_in", 900)),
    )


def poll_for_github_token(session: DeviceFlowSession) -> str | None:
    """Make ONE poll attempt for the user's approval.

    Returns the GitHub access token once the user has approved the device
    code, or ``None`` if still pending. Raises :class:`CopilotAuthError` if
    the code expired or was denied. Callers (CLI: blocking loop respecting
    ``session.interval``; web: one call per HTTP request) decide the cadence.
    """
    if time.time() > session.expires_at:
        raise CopilotAuthError("Device code expired -- start the login again.")

    status, payload = _http_json(
        f"{GITHUB_BASE_URL}/login/oauth/access_token",
        method="POST",
        headers=_github_headers(),
        body={
            "client_id": GITHUB_CLIENT_ID,
            "device_code": session.device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
    )
    if not payload:
        return None

    if payload.get("access_token"):
        return payload["access_token"]

    error = payload.get("error")
    if error == "authorization_pending":
        return None
    if error == "slow_down":
        return None
    if error in ("expired_token", "access_denied"):
        raise CopilotAuthError(f"GitHub device login {error.replace('_', ' ')}.")
    # Unknown error shape -- treat as still-pending rather than failing hard,
    # matching the bridge's own tolerant polling behavior.
    return None


def exchange_for_copilot_token(github_token: str) -> tuple[str, int]:
    """Exchange a GitHub token for a short-lived Copilot bearer token.

    Returns ``(copilot_token, refresh_in_seconds)``.
    """
    status, payload = _http_json(
        f"{GITHUB_API_BASE_URL}/copilot_internal/v2/token",
        method="GET",
        headers={**_github_headers(), "Authorization": f"token {github_token}"},
    )
    if status != 200 or not payload or not payload.get("token"):
        raise CopilotAuthError(
            f"Failed to get a Copilot token (HTTP {status}). "
            "Your GitHub account may not have an active Copilot subscription."
        )
    return payload["token"], int(payload.get("refresh_in", 1500))


def complete_login(github_token: str) -> None:
    """Persist a GitHub token and immediately exchange it for a Copilot token."""
    copilot_token, refresh_in = exchange_for_copilot_token(github_token)
    _save_token_cache({
        "github_token": github_token,
        "copilot_token": copilot_token,
        "copilot_token_expires_at": time.time() + refresh_in,
    })


# ---------------------------------------------------------------------------
# Token retrieval (lazy refresh on use)
# ---------------------------------------------------------------------------

def get_valid_copilot_token() -> str:
    """Return a Copilot bearer token, refreshing it if it's expired/near-expiry.

    Raises :class:`CopilotAuthError` if never logged in. Refreshing lazily
    (right before use) rather than on a background timer keeps this simple
    and correct: the token is only ever needed exactly when a request is
    about to be made.
    """
    cache = _load_token_cache()
    github_token = cache.get("github_token")
    if not github_token:
        raise CopilotAuthError(
            "Not connected to GitHub Copilot. Run 'clanker copilot-login' or "
            "connect via the web config UI (clanker config)."
        )

    copilot_token = cache.get("copilot_token")
    expires_at = cache.get("copilot_token_expires_at", 0)
    if copilot_token and time.time() < (expires_at - _REFRESH_SKEW_SECONDS):
        return copilot_token

    logger.info("Copilot token expired or missing -- refreshing.")
    copilot_token, refresh_in = exchange_for_copilot_token(github_token)
    cache["copilot_token"] = copilot_token
    cache["copilot_token_expires_at"] = time.time() + refresh_in
    _save_token_cache(cache)
    return copilot_token


# ---------------------------------------------------------------------------
# Model discovery
# ---------------------------------------------------------------------------

def list_copilot_models() -> list[dict[str, Any]]:
    """Fetch the raw model capability list from Copilot's /models endpoint."""
    token = get_valid_copilot_token()
    status, payload = _http_json(
        f"{COPILOT_BASE_URL}/models",
        method="GET",
        headers={**copilot_request_headers(), "Authorization": f"Bearer {token}"},
    )
    if status != 200 or not payload:
        raise CopilotAuthError(f"Failed to list Copilot models (HTTP {status})")
    return payload.get("data", [])


# Prefix used for auto-synced model entries, so they're visually distinct from
# a user's manually-configured models and safely identifiable for re-sync.
COPILOT_MODEL_NAME_PREFIX = "copilot:"


def sync_copilot_models() -> int:
    """Auto-populate one ModelConfig per Copilot model. Returns the count synced.

    Idempotent: re-running updates existing ``copilot:*`` entries in place
    (via the existing ``add_model``, which already dedupes by name) rather
    than duplicating them. Models the account hasn't accepted upstream terms
    for are skipped with a warning, not a hard failure.
    """
    # Imported lazily to avoid a hypothetical import-order issue between
    # config.models and this module (models.py imports copilot_auth, not the
    # reverse, but this keeps the dependency direction explicit).
    from clanker.config.models import ModelConfig, add_model

    models = list_copilot_models()
    synced = 0
    for model in models:
        model_id = model.get("id")
        if not model_id:
            continue

        policy = model.get("policy") or {}
        if policy.get("state") and policy["state"] != "enabled":
            logger.warning(
                "Skipping Copilot model '%s' -- policy state is '%s' "
                "(may need acceptance in the GitHub Copilot settings).",
                model_id, policy["state"],
            )
            continue

        limits = (model.get("capabilities") or {}).get("limits") or {}
        max_input_tokens = limits.get("max_context_window_tokens")
        max_output_tokens = limits.get("max_output_tokens")

        add_model(ModelConfig(
            name=f"{COPILOT_MODEL_NAME_PREFIX}{model_id}",
            provider="GitHubCopilot",
            model=model_id,
            max_input_tokens=max_input_tokens,
            max_tokens=max_output_tokens,
        ))
        synced += 1

    logger.info("Synced %d Copilot model(s).", synced)
    return synced
