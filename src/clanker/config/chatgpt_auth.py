"""ChatGPT account login and Codex model discovery, without a local proxy.

Protocol reference: EvanZhouDev/openai-oauth (Apache-2.0), dev proxy/core.
Only Clanker's own credential file is accessed; Codex credentials are untouched.
"""

from __future__ import annotations

import base64
import errno
import hashlib
import json
import os
import re
import secrets
import socket
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

# Public PKCE client registration; no client secret is used.
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
TOKEN_URL = "https://auth.openai.com/oauth/token"
BASE_URL = "https://chatgpt.com/backend-api/codex"
REDIRECT_URI = "http://localhost:1455/auth/callback"
TOKEN_PATH = Path.home() / ".clanker" / "chatgpt_auth.json"
DEFAULT_CODEX_VERSION = "0.144.1"
_token_lock = threading.RLock()
_version_lock = threading.Lock()
_version_cache: tuple[str, float] = (DEFAULT_CODEX_VERSION, 0)


class ChatGPTAuthError(ValueError):
    """An actionable account error that never includes token response bodies."""


def _request(
    url: str,
    *,
    form: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    try:
        with httpx.Client(timeout=30) as client:
            if form is not None:
                response = client.post(url, data=form)
            elif body is not None:
                response = client.post(url, json=body)
            else:
                response = client.get(url, headers=headers)
            try:
                data = response.json()
            except ValueError:
                data = {}
            return response.status_code, data if isinstance(data, dict) else {}
    except httpx.HTTPError as exc:
        raise ChatGPTAuthError(
            "Could not contact OpenAI. Check your connection and retry."
        ) from exc


def _load_cache() -> dict[str, Any]:
    try:
        data = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cache(data: dict[str, Any]) -> None:
    name = None
    try:
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(dir=TOKEN_PATH.parent, prefix=".chatgpt-")
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.replace(name, TOKEN_PATH)
    except OSError as exc:
        raise ChatGPTAuthError(
            "Could not securely save ChatGPT login. Check ~/.clanker write permissions."
        ) from exc
    finally:
        if name:
            with suppress(OSError):
                os.unlink(name)


def _claims(token: str | None) -> dict[str, Any]:
    # Decode only to extract account metadata from the HTTPS token response;
    # these unverified claims are never used to authenticate a caller.
    try:
        encoded = (token or "").split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        return data if isinstance(data, dict) else {}
    except (ValueError, IndexError, TypeError):
        return {}


def _update_tokens(cache: dict[str, Any], tokens: dict[str, Any]) -> dict[str, Any]:
    cache = dict(cache)
    for key in ("access_token", "refresh_token", "id_token"):
        if isinstance(tokens.get(key), str) and tokens[key]:
            cache[key] = tokens[key]
    identity, access = _claims(cache.get("id_token")), _claims(cache.get("access_token"))
    for claims in (identity, access):
        account = claims.get("https://api.openai.com/auth") or {}
        if not isinstance(account, dict):
            continue
        account_id = account.get("chatgpt_account_id") or claims.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id:
            cache["account_id"] = account_id
            cache["is_fedramp"] = account.get("chatgpt_account_is_fedramp") is True
            break
    profile = identity.get("https://api.openai.com/profile") or {}
    cache["email"] = (
        identity.get("email")
        or (profile.get("email") if isinstance(profile, dict) else None)
        or cache.get("email")
    )
    try:
        lifetime = tokens.get("expires_in")
        cache["expires_at"] = (
            time.time() + int(lifetime)
            if lifetime is not None
            else float(access.get("exp", time.time() + 3600))
        )
    except (ValueError, TypeError):
        raise ChatGPTAuthError(
            "OpenAI returned an invalid token lifetime. Start login again."
        ) from None
    if not all(cache.get(key) for key in ("access_token", "refresh_token", "account_id")):
        raise ChatGPTAuthError(
            "OpenAI did not return a complete ChatGPT account session. Start login again."
        )
    return cache


def connection_status() -> dict[str, Any]:
    cache = _load_cache()
    return {
        "connected": bool(cache.get("refresh_token") and cache.get("account_id")),
        "email": cache.get("email"),
    }


def disconnect() -> None:
    with _token_lock:
        TOKEN_PATH.unlink(missing_ok=True)


def get_credentials() -> dict[str, Any]:
    with _token_lock:
        cache = _load_cache()
        if not cache.get("refresh_token") or not cache.get("account_id"):
            raise ChatGPTAuthError("Not connected to ChatGPT. Run 'clanker openai-login'.")
        try:
            expires_at = float(cache.get("expires_at", 0))
        except (TypeError, ValueError):
            expires_at = 0
        if cache.get("access_token") and time.time() < expires_at - 60:
            return cache
        status, tokens = _request(
            TOKEN_URL,
            body={
                "grant_type": "refresh_token",
                "refresh_token": cache["refresh_token"],
                "client_id": CLIENT_ID,
            },
        )
        if status != 200 or not tokens.get("access_token"):
            error = tokens.get("error")
            code = error.get("code") if isinstance(error, dict) else error
            if (
                code
                in {
                    "invalid_grant",
                    "refresh_token_expired",
                    "refresh_token_reused",
                    "refresh_token_invalidated",
                }
                or status == 401
            ):
                disconnect()
                raise ChatGPTAuthError(
                    "ChatGPT login expired or was revoked. Run 'clanker openai-login' again."
                )
            raise ChatGPTAuthError(
                f"ChatGPT token refresh failed (HTTP {status}). Try again later."
            )
        cache = _update_tokens(cache, tokens)
        _save_cache(cache)
        return cache


def api_headers(credentials: dict[str, Any]) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {credentials['access_token']}",
        "chatgpt-account-id": credentials["account_id"],
    }
    if credentials.get("is_fedramp"):
        headers["X-OpenAI-Fedramp"] = "true"
    return headers


def _codex_version() -> str:
    global _version_cache
    with _version_lock:
        if time.time() < _version_cache[1]:
            return _version_cache[0]
        version = DEFAULT_CODEX_VERSION
        try:
            status, data = _request("https://registry.npmjs.org/@openai/codex/latest")
            if status == 200 and re.fullmatch(r"\d+\.\d+\.\d+", str(data.get("version", ""))):
                version = data["version"]
        except ChatGPTAuthError:
            pass
        _version_cache = (version, time.time() + 3600)
        return version


def model_info(model_id: str) -> dict[str, Any]:
    catalogue = _load_cache().get("models")
    metadata = catalogue.get(model_id) if isinstance(catalogue, dict) else None
    return metadata if isinstance(metadata, dict) else {}


def sync_models() -> int:
    from clanker.config.models import ModelConfig, get_models_config, save_models_config

    credentials = get_credentials()
    status, data = _request(
        f"{BASE_URL}/models?client_version={_codex_version()}", headers=api_headers(credentials)
    )
    if status != 200:
        raise ChatGPTAuthError(
            f"ChatGPT model discovery failed (HTTP {status}). Check account access or reconnect."
        )
    raw = data.get("models")
    if not isinstance(raw, list):
        raise ChatGPTAuthError("ChatGPT returned an invalid model catalogue. Try refreshing again.")
    config = get_models_config()
    existing = {model.name.casefold(): model for model in config.models}
    catalogue = {}
    for metadata in raw:
        if not isinstance(metadata, dict):
            continue
        model_id = metadata.get("slug")
        if not isinstance(model_id, str) or not model_id or "image" in model_id.lower():
            continue
        if (
            metadata.get("supported_in_api") is False
            or metadata.get("visibility", "list") != "list"
        ):
            continue
        # Only persist capabilities used by the adapter, never arbitrary response fields.
        catalogue[model_id] = {
            key: metadata[key]
            for key in (
                "use_responses_lite",
                "default_reasoning_level",
                "support_verbosity",
                "default_verbosity",
            )
            if key in metadata
        }
        name = f"chatgpt:{model_id}"
        previous = existing.get(name.casefold())
        limit = (
            metadata.get("max_input_tokens")
            or metadata.get("context_window")
            or metadata.get("input_token_limit")
        )
        limit = (
            limit if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0 else None
        )
        entry = ModelConfig(name=name, provider="ChatGPT", model=model_id, max_input_tokens=limit)
        if previous:
            updates: dict[str, Any] = {"provider": "ChatGPT", "model": model_id}
            if limit:
                updates["max_input_tokens"] = limit
            entry = previous.model_copy(update=updates)
        existing[name.casefold()] = entry
    if not catalogue:
        raise ChatGPTAuthError("No supported coding models were returned for this ChatGPT account.")
    with _token_lock:
        cache = get_credentials()
        if cache["account_id"] != credentials["account_id"]:
            raise ChatGPTAuthError(
                "ChatGPT account changed during discovery. Refresh models again."
            )
        cache["models"] = catalogue
        _save_cache(cache)
        config.models = list(existing.values())
        if not config.default:
            config.default = f"chatgpt:{next(iter(catalogue))}"
        save_models_config(config)
    return len(catalogue)


@dataclass
class LoginSession:
    url: str = ""
    state: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
    verifier: str = field(default_factory=lambda: secrets.token_urlsafe(48), repr=False)
    expires_at: float = field(default_factory=lambda: time.time() + 600)
    code: str | None = field(default=None, repr=False)
    error: str | None = None
    result: int | None = None
    completing: bool = False
    servers: list[ThreadingHTTPServer] = field(default_factory=list, repr=False)
    timer: threading.Timer | None = field(default=None, repr=False)
    lock: Any = field(default_factory=threading.Lock, repr=False)

    def close(self) -> None:
        with self.lock:
            servers, self.servers = self.servers, []
        if self.timer:
            self.timer.cancel()
        for server in servers:
            server.shutdown()
            server.server_close()

    def cancel(self, *, close: bool = True) -> None:
        with self.lock:
            self.error = "ChatGPT login cancelled."
            self.code = None
        if close:
            self.close()


def submit_callback(session: LoginSession, callback_url: str) -> None:
    parsed = urlsplit(callback_url)
    if parsed.path != "/auth/callback":
        raise ChatGPTAuthError("Use the full /auth/callback URL from this login attempt.")
    query = parse_qs(parsed.query)
    if not secrets.compare_digest(query.get("state", [""])[0], session.state):
        raise ChatGPTAuthError(
            "Callback state does not match this ChatGPT login. Use the current login link."
        )
    with session.lock:
        if (
            session.error
            or session.code
            or session.completing
            or session.result is not None
            or time.time() >= session.expires_at
        ):
            raise ChatGPTAuthError("This ChatGPT login is no longer accepting callbacks.")
        if query.get("error"):
            session.error = "ChatGPT authorization was denied. Start login again."
        elif query.get("code"):
            session.code = query["code"][0]
        else:
            raise ChatGPTAuthError("The callback URL does not contain an authorization code.")


def start_login(*, manual: bool = False) -> LoginSession:
    session = LoginSession()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            try:
                submit_callback(session, self.path)
                status, text = 200, "Authorization received. Return to Clanker to finish login."
            except ChatGPTAuthError:
                status, text = 400, "Invalid or expired ChatGPT callback. Return to Clanker."
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(text.encode())

        def log_message(self, format: str, *args: Any) -> None:
            pass  # Callback codes must never enter request logs.

    class IPv6Server(ThreadingHTTPServer):
        address_family = socket.AF_INET6

    if not manual:
        for host, server_class in (("127.0.0.1", ThreadingHTTPServer), ("::1", IPv6Server)):
            try:
                server = server_class((host, 1455), Handler)
            except OSError as exc:
                if host == "::1" and exc.errno in {
                    errno.EAFNOSUPPORT,
                    errno.EADDRNOTAVAIL,
                    errno.EPROTONOSUPPORT,
                }:
                    continue  # IPv6 may be unavailable on this machine.
                session.close()
                raise ChatGPTAuthError(
                    "Cannot open ChatGPT callback port 1455. Close other Codex/OpenAI login attempts, "
                    "or use 'clanker openai-login --no-browser --manual'."
                ) from None
            server.daemon_threads = True
            session.servers.append(server)
            threading.Thread(target=server.serve_forever, daemon=True).start()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(session.verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    session.url = "https://auth.openai.com/oauth/authorize?" + urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": "openid profile email offline_access",
            "state": session.state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
        }
    )
    session.timer = threading.Timer(600, session.close)
    session.timer.daemon = True
    session.timer.start()
    return session


def poll_login(session: LoginSession) -> int | None:
    with session.lock:
        if session.error:
            raise ChatGPTAuthError(session.error)
        if session.result is not None:
            return session.result
        if time.time() >= session.expires_at:
            raise ChatGPTAuthError("ChatGPT login expired. Start login again.")
        if session.completing or not session.code:
            return None
        code, session.code = session.code, None
        session.completing = True
    session.close()
    try:
        status, tokens = _request(
            TOKEN_URL,
            form={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": session.verifier,
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
            },
        )
        if status != 200:
            raise ChatGPTAuthError(
                f"ChatGPT token exchange failed (HTTP {status}). Start login again."
            )
        cache = _update_tokens({}, tokens)
        with _token_lock, session.lock:
            if session.error or time.time() >= session.expires_at:
                raise ChatGPTAuthError(session.error or "ChatGPT login expired. Start login again.")
            _save_cache(cache)
        result = sync_models()
    except ChatGPTAuthError as exc:
        with session.lock:
            session.error = str(exc)
        raise
    with session.lock:
        if session.error:
            raise ChatGPTAuthError(session.error)
        session.result = result
    return result
