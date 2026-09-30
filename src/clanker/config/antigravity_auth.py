"""Google OAuth and model discovery for the unofficial Antigravity API.

Protocol reference: badrisnarayanan/antigravity-claude-proxy (MIT).
Credentials belong to Clanker; we never read another app's token database.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import secrets
import tempfile
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

# Installed-app OAuth client published by the protocol reference. This is a
# public client registration, not a user's credential. PKCE protects the code.
CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
CLIENT_SECRET = "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"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = (
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs",
)
ENDPOINTS = (
    "https://daily-cloudcode-pa.googleapis.com",
    "https://cloudcode-pa.googleapis.com",
)
TOKEN_PATH = Path.home() / ".clanker" / "antigravity_auth.json"
MODEL_PREFIX = "antigravity:"
LOGIN_NOTICE = (
    "Antigravity is an unofficial Google integration. The reference project "
    "reports account bans associated with its use."
)
_token_lock = threading.RLock()


class AntigravityAuthError(ValueError):
    """An actionable authentication or API error, without token response bodies."""


def api_headers(token: str) -> dict[str, str]:
    system = {"Darwin": "darwin", "Windows": "win32"}.get(platform.system(), "linux")
    architecture = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x64"
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": f"antigravity/2.0.3 {system}/{architecture}",
        "X-Client-Name": "antigravity",
        "X-Client-Version": "1.110.0",
    }


def _metadata() -> dict[str, int]:
    system, arm = platform.system(), platform.machine().lower() in {"arm64", "aarch64"}
    value = {"Darwin": 2 if arm else 1, "Linux": 4 if arm else 3, "Windows": 5}.get(system, 0)
    return {"ideType": 9, "platform": value, "pluginType": 2}


def _request(
    url: str,
    *,
    form: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    token: str = "",
) -> tuple[int, dict[str, Any]]:
    try:
        with httpx.Client(timeout=30) as client:
            if form is not None:
                response = client.post(url, data=form)
            elif body is not None:
                response = client.post(url, json=body, headers=api_headers(token))
            else:
                response = client.get(url, headers=api_headers(token))
            try:
                data = response.json()
            except ValueError:
                data = {}
            return response.status_code, data if isinstance(data, dict) else {}
    except httpx.HTTPError as exc:
        # Never expose URLs from OAuth responses, request headers, or bodies.
        raise AntigravityAuthError(
            "Could not contact Google. Check your connection and try again."
        ) from exc


def _load_cache() -> dict[str, Any]:
    try:
        value = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cache(data: dict[str, Any]) -> None:
    # mkstemp creates with 0600 before writing, and replace is atomic. Close the
    # descriptor before replacing so this works on Windows as well.
    name: str | None = None
    try:
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(dir=TOKEN_PATH.parent, prefix=".antigravity-")
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.replace(name, TOKEN_PATH)
    except OSError as exc:
        raise AntigravityAuthError(
            "Could not securely save Google credentials. Check write permissions for ~/.clanker."
        ) from exc
    finally:
        if name:
            with suppress(OSError):
                os.unlink(name)


def connection_status() -> dict[str, Any]:
    cache = _load_cache()
    return {"connected": bool(cache.get("refresh_token")), "email": cache.get("email")}


def disconnect() -> None:
    with _token_lock:
        TOKEN_PATH.unlink(missing_ok=True)


def get_credentials() -> dict[str, Any]:
    """Refresh before each request, including within long turns and subagents."""
    with _token_lock:
        cache = _load_cache()
        if not cache.get("refresh_token"):
            raise AntigravityAuthError(
                "Not connected to Google Antigravity. Run 'clanker antigravity-login'."
            )
        if cache.get("access_token") and time.time() < cache.get("expires_at", 0) - 60:
            return cache
        status, data = _request(
            TOKEN_URL,
            form={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "refresh_token": cache["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
        if status != 200 or not data.get("access_token"):
            if data.get("error") == "invalid_grant":
                disconnect()
                raise AntigravityAuthError(
                    "Google login expired or was revoked. Run 'clanker antigravity-login' again."
                )
            raise AntigravityAuthError(
                f"Google token refresh failed (HTTP {status}). Try again later."
            )
        cache.update(
            access_token=data["access_token"],
            expires_at=time.time() + int(data.get("expires_in", 3600)),
        )
        if data.get("refresh_token"):
            cache["refresh_token"] = data["refresh_token"]
        _save_cache(cache)
        return cache


def api_request(action: str, body: dict[str, Any], *, token: str) -> tuple[dict[str, Any], str]:
    """Try the documented endpoint order, without retrying account denials."""
    last_status = 0
    for endpoint in ENDPOINTS:
        status, data = _request(f"{endpoint}/v1internal:{action}", body=body, token=token)
        if status == 200:
            return data, endpoint
        last_status = status
        if status in {401, 403}:
            raise AntigravityAuthError(
                f"Google denied Antigravity access (HTTP {status}). Check account access or reconnect."
            )
    raise AntigravityAuthError(
        f"Antigravity {action} failed (HTTP {last_status}). Try again later."
    )


def _project_id(data: dict[str, Any]) -> str | None:
    project = data.get("cloudaicompanionProject")
    return (
        project
        if isinstance(project, str)
        else project.get("id")
        if isinstance(project, dict)
        else None
    )


def complete_login(
    code: str, verifier: str, redirect_uri: str, *, session: LoginSession | None = None
) -> None:
    status, tokens = _request(
        TOKEN_URL,
        form={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
    )
    if status != 200 or not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise AntigravityAuthError(
            f"Google token exchange failed (HTTP {status}). Start login again and grant access."
        )
    token = tokens["access_token"]
    status, profile = _request("https://www.googleapis.com/oauth2/v1/userinfo", token=token)
    if status != 200:
        raise AntigravityAuthError(
            f"Could not retrieve Google account information (HTTP {status})."
        )
    data, endpoint = api_request("loadCodeAssist", {"metadata": _metadata()}, token=token)
    project = _project_id(data)
    if not project:
        tiers = data.get("allowedTiers") or []
        tier = next((item for item in tiers if item.get("isDefault")), tiers[0] if tiers else {})
        if not tier.get("id"):
            raise AntigravityAuthError(
                "Google did not provide an Antigravity project or eligible tier. Check account eligibility."
            )
        for attempt in range(10):
            result, endpoint = api_request(
                "onboardUser",
                {
                    "tierId": tier["id"],
                    "metadata": _metadata(),
                },
                token=token,
            )
            if result.get("done"):
                project = _project_id(result.get("response") or {})
                break
            if attempt < 9:
                time.sleep(2)
    if not project:
        raise AntigravityAuthError(
            "Google project provisioning is incomplete. Try login again later."
        )
    with _token_lock:
        cache = {
            "access_token": token,
            "refresh_token": tokens["refresh_token"],
            "expires_at": time.time() + int(tokens.get("expires_in", 3600)),
            "email": profile.get("email"),
            "project_id": project,
            "endpoint": endpoint,
        }
        if session:
            with session.lock:
                if session.error or time.time() >= session.expires_at:
                    raise AntigravityAuthError(
                        "Google login cancelled or expired before completion."
                    )
                _save_cache(cache)
        else:
            _save_cache(cache)


def sync_models() -> int:
    from clanker.config.models import ModelConfig, get_models_config, save_models_config

    credentials = get_credentials()
    data, _ = api_request(
        "fetchAvailableModels",
        {"project": credentials["project_id"]},
        token=credentials["access_token"],
    )
    entries = []
    for model_id, metadata in (data.get("models") or {}).items():
        if not model_id.startswith(("claude-", "gemini-")) or "image" in model_id.lower():
            continue
        # ModelConfig fills documented defaults only when metadata is absent.
        entries.append(
            ModelConfig(
                name=f"{MODEL_PREFIX}{model_id}",
                provider="Antigravity",
                model=model_id,
                max_input_tokens=metadata.get("maxInputTokens") or metadata.get("inputTokenLimit"),
                max_tokens=metadata.get("maxOutputTokens") or metadata.get("outputTokenLimit"),
                thinking_enabled="thinking" in model_id,
            )
        )
    if not entries:
        raise AntigravityAuthError(
            "No supported Claude or Gemini models were returned for this account."
        )
    config = get_models_config()
    existing = {model.name.casefold(): model for model in config.models}
    for entry in entries:
        previous = existing.get(entry.name.casefold())
        if previous:
            # Keep user settings and manually supplied limits on refresh.
            updates: dict[str, Any] = {"provider": "Antigravity", "model": entry.model}
            if entry.max_tokens:
                updates["max_tokens"] = entry.max_tokens
            metadata = (data.get("models") or {}).get(entry.model, {})
            if metadata.get("maxInputTokens") or metadata.get("inputTokenLimit"):
                updates["max_input_tokens"] = entry.max_input_tokens
            entry = previous.model_copy(update=updates)
        existing[entry.name.casefold()] = entry
    config.models = list(existing.values())
    if not config.default:
        config.default = entries[0].name
    save_models_config(config)
    return len(entries)


@dataclass
class LoginSession:
    url: str = ""
    redirect_uri: str = ""
    state: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
    verifier: str = field(default_factory=lambda: secrets.token_urlsafe(48), repr=False)
    expires_at: float = field(default_factory=lambda: time.time() + 600)
    code: str | None = field(default=None, repr=False)
    error: str | None = None
    result: int | None = None
    completing: bool = False
    server: ThreadingHTTPServer | None = field(default=None, repr=False)
    timer: threading.Timer | None = field(default=None, repr=False)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def close(self) -> None:
        with self.lock:
            server, self.server = self.server, None
        if self.timer:
            self.timer.cancel()
        if server:
            server.shutdown()
            server.server_close()

    def cancel(self, *, close: bool = True) -> None:
        with self.lock:
            self.error = "Google login cancelled."
            self.code = None
        if close:
            self.close()


def submit_callback(session: LoginSession, callback_url: str) -> None:
    query = parse_qs(urlsplit(callback_url).query)
    state = query.get("state", [""])[0]
    if not secrets.compare_digest(state, session.state):
        raise AntigravityAuthError(
            "Google callback state does not match this login. Use the current login link."
        )
    with session.lock:
        if (
            time.time() >= session.expires_at
            or session.error
            or session.completing
            or session.result is not None
        ):
            raise AntigravityAuthError("This Google login is no longer accepting callbacks.")
        if query.get("error"):
            session.error = "Google authorization was denied. Start login again to retry."
        elif query.get("code"):
            session.code = query["code"][0]
        else:
            raise AntigravityAuthError("The callback URL does not contain an authorization code.")


def start_login() -> LoginSession:
    session = LoginSession()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if urlsplit(self.path).path != "/oauth-callback":
                self.send_error(404)
                return
            try:
                submit_callback(session, self.path)
                status, text = 200, "Authorization received. Return to Clanker to complete login."
            except AntigravityAuthError:
                status, text = 400, "Invalid or expired Google login callback. Return to Clanker."
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(text.encode())

        def log_message(self, format: str, *args: Any) -> None:
            pass  # Callback URLs contain authorization codes; never log them.

    for port in range(51121, 51127):
        try:
            session.server = ThreadingHTTPServer(("127.0.0.1", port), CallbackHandler)
            break
        except OSError:
            continue
    if not session.server:
        raise AntigravityAuthError(
            "Cannot open a Google login callback port (51121–51126). Close other login attempts and retry."
        )
    session.server.daemon_threads = True
    session.redirect_uri = f"http://localhost:{session.server.server_port}/oauth-callback"
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(session.verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    session.url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id": CLIENT_ID,
            "redirect_uri": session.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": session.state,
        }
    )
    threading.Thread(target=session.server.serve_forever, daemon=True).start()
    session.timer = threading.Timer(600, session.close)
    session.timer.daemon = True
    session.timer.start()
    return session


def poll_login(session: LoginSession) -> int | None:
    with session.lock:
        if session.error:
            raise AntigravityAuthError(session.error)
        if session.result is not None:
            return session.result
        if session.completing:
            return None
        if time.time() >= session.expires_at:
            raise AntigravityAuthError("Google login expired. Start login again.")
        if not session.code:
            return None
        code, session.code = session.code, None
        session.completing = True
    session.close()
    try:
        complete_login(code, session.verifier, session.redirect_uri, session=session)
        result = sync_models()
    except AntigravityAuthError as exc:
        with session.lock:
            session.error = str(exc)
        raise
    with session.lock:
        session.result = result
    return result
