"""Tests for native GitHub Copilot integration (device-code login, token cache,
model auto-population, and the provider wiring in create_llm_from_config).

Everything here is stubbed -- no real network calls, no real GitHub/Copilot
account needed.
"""

from __future__ import annotations

import json
import time

import pytest

from clanker.config.copilot_auth import (
    COPILOT_MODEL_NAME_PREFIX,
    CopilotAuthError,
    DeviceFlowSession,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def copilot_auth(monkeypatch, tmp_path):
    """The copilot_auth module with its token cache redirected to tmp_path."""
    import clanker.config.copilot_auth as ca

    monkeypatch.setattr(ca, "COPILOT_TOKEN_PATH", tmp_path / "copilot_auth.json")
    return ca


@pytest.fixture
def models_config(monkeypatch, tmp_path):
    """clanker.config.models with MODELS_CONFIG_PATH redirected to tmp_path."""
    import clanker.config.models as models_mod

    monkeypatch.setattr(models_mod, "MODELS_CONFIG_PATH", tmp_path / "models.json")
    return models_mod


def _fake_http_json(responses):
    """Build a fake _http_json that returns responses in call order.

    `responses` is a list of (status, payload) tuples; each call to the fake
    pops the next one. Raises IndexError (surfaced as a test failure) if
    called more times than expected.
    """
    calls = []
    remaining = list(responses)

    def fake(url, **kwargs):
        calls.append((url, kwargs))
        return remaining.pop(0)

    fake.calls = calls
    return fake


# ---------------------------------------------------------------------------
# Device flow
# ---------------------------------------------------------------------------

class TestDeviceFlow:
    def test_start_device_flow_success(self, copilot_auth, monkeypatch):
        monkeypatch.setattr(
            copilot_auth,
            "_http_json",
            _fake_http_json([(200, {
                "device_code": "dc123",
                "user_code": "ABCD-1234",
                "verification_uri": "https://github.com/login/device",
                "interval": 5,
                "expires_in": 900,
            })]),
        )
        session = copilot_auth.start_device_flow()
        assert session.device_code == "dc123"
        assert session.user_code == "ABCD-1234"
        assert session.verification_uri == "https://github.com/login/device"
        assert session.interval == 5

    def test_start_device_flow_http_error(self, copilot_auth, monkeypatch):
        monkeypatch.setattr(copilot_auth, "_http_json", _fake_http_json([(400, None)]))
        with pytest.raises(CopilotAuthError):
            copilot_auth.start_device_flow()

    def test_poll_pending(self, copilot_auth, monkeypatch):
        session = DeviceFlowSession(
            device_code="dc", user_code="U", verification_uri="https://x",
            interval=5, expires_at=time.time() + 900,
        )
        monkeypatch.setattr(
            copilot_auth, "_http_json",
            _fake_http_json([(400, {"error": "authorization_pending"})]),
        )
        assert copilot_auth.poll_for_github_token(session) is None

    def test_poll_success(self, copilot_auth, monkeypatch):
        session = DeviceFlowSession(
            device_code="dc", user_code="U", verification_uri="https://x",
            interval=5, expires_at=time.time() + 900,
        )
        monkeypatch.setattr(
            copilot_auth, "_http_json",
            _fake_http_json([(200, {"access_token": "gh_abc123"})]),
        )
        assert copilot_auth.poll_for_github_token(session) == "gh_abc123"

    def test_poll_expired_code_raises(self, copilot_auth, monkeypatch):
        session = DeviceFlowSession(
            device_code="dc", user_code="U", verification_uri="https://x",
            interval=5, expires_at=time.time() + 900,
        )
        monkeypatch.setattr(
            copilot_auth, "_http_json",
            _fake_http_json([(400, {"error": "expired_token"})]),
        )
        with pytest.raises(CopilotAuthError):
            copilot_auth.poll_for_github_token(session)

    def test_poll_after_local_expiry_raises_without_http_call(self, copilot_auth, monkeypatch):
        session = DeviceFlowSession(
            device_code="dc", user_code="U", verification_uri="https://x",
            interval=5, expires_at=time.time() - 1,  # already expired
        )
        fake = _fake_http_json([])
        monkeypatch.setattr(copilot_auth, "_http_json", fake)
        with pytest.raises(CopilotAuthError):
            copilot_auth.poll_for_github_token(session)
        assert fake.calls == []  # never made a network call for an already-expired code

    def test_exchange_for_copilot_token_success(self, copilot_auth, monkeypatch):
        monkeypatch.setattr(
            copilot_auth, "_http_json",
            _fake_http_json([(200, {"token": "cp_token", "refresh_in": 1500})]),
        )
        token, refresh_in = copilot_auth.exchange_for_copilot_token("gh_abc")
        assert token == "cp_token"
        assert refresh_in == 1500

    def test_exchange_for_copilot_token_failure(self, copilot_auth, monkeypatch):
        monkeypatch.setattr(copilot_auth, "_http_json", _fake_http_json([(401, None)]))
        with pytest.raises(CopilotAuthError):
            copilot_auth.exchange_for_copilot_token("gh_abc")


# ---------------------------------------------------------------------------
# Token cache / get_valid_copilot_token
# ---------------------------------------------------------------------------

class TestTokenCache:
    def test_not_connected_raises(self, copilot_auth):
        with pytest.raises(CopilotAuthError):
            copilot_auth.get_valid_copilot_token()

    def test_cached_valid_token_no_refresh(self, copilot_auth, monkeypatch):
        copilot_auth._save_token_cache({
            "github_token": "gh",
            "copilot_token": "cp_cached",
            "copilot_token_expires_at": time.time() + 1000,
        })

        def boom(*a, **k):
            raise AssertionError("should not refresh a still-valid token")

        monkeypatch.setattr(copilot_auth, "exchange_for_copilot_token", boom)
        assert copilot_auth.get_valid_copilot_token() == "cp_cached"

    def test_expired_token_triggers_exactly_one_refresh(self, copilot_auth, monkeypatch):
        copilot_auth._save_token_cache({
            "github_token": "gh",
            "copilot_token": "stale",
            "copilot_token_expires_at": time.time() - 10,
        })
        calls = []

        def fake_exchange(github_token):
            calls.append(github_token)
            return ("fresh", 1500)

        monkeypatch.setattr(copilot_auth, "exchange_for_copilot_token", fake_exchange)
        token = copilot_auth.get_valid_copilot_token()
        assert token == "fresh"
        assert calls == ["gh"]

        # Cache now holds the fresh token; calling again must not re-exchange.
        monkeypatch.setattr(
            copilot_auth, "exchange_for_copilot_token",
            lambda *a: (_ for _ in ()).throw(AssertionError("should not re-exchange")),
        )
        assert copilot_auth.get_valid_copilot_token() == "fresh"

    def test_token_file_permissions(self, copilot_auth):
        copilot_auth._save_token_cache({"github_token": "gh"})
        mode = copilot_auth.COPILOT_TOKEN_PATH.stat().st_mode & 0o777
        assert mode == 0o600

    def test_is_connected_and_disconnect(self, copilot_auth):
        assert not copilot_auth.is_connected()
        copilot_auth._save_token_cache({"github_token": "gh"})
        assert copilot_auth.is_connected()
        copilot_auth.disconnect()
        assert not copilot_auth.is_connected()

    def test_complete_login_persists_both_tokens(self, copilot_auth, monkeypatch):
        monkeypatch.setattr(
            copilot_auth, "exchange_for_copilot_token",
            lambda gh: ("cp_new", 1500),
        )
        copilot_auth.complete_login("gh_new")
        cache = json.loads(copilot_auth.COPILOT_TOKEN_PATH.read_text())
        assert cache["github_token"] == "gh_new"
        assert cache["copilot_token"] == "cp_new"


# ---------------------------------------------------------------------------
# Model sync
# ---------------------------------------------------------------------------

class TestSyncCopilotModels:
    def _stub_connected(self, copilot_auth, monkeypatch):
        copilot_auth._save_token_cache({
            "github_token": "gh", "copilot_token": "cp",
            "copilot_token_expires_at": time.time() + 1000,
        })

    def test_creates_one_model_per_entry_with_real_limits(
        self, copilot_auth, models_config, monkeypatch
    ):
        self._stub_connected(copilot_auth, monkeypatch)
        monkeypatch.setattr(copilot_auth, "list_copilot_models", lambda: [
            {
                "id": "claude-sonnet-5",
                "capabilities": {"limits": {
                    "max_context_window_tokens": 200_000,
                    "max_output_tokens": 64_000,
                }},
            },
            {
                "id": "gpt-5.5",
                "capabilities": {"limits": {
                    "max_context_window_tokens": 400_000,
                    "max_output_tokens": 128_000,
                }},
            },
        ])

        synced = copilot_auth.sync_copilot_models()
        assert synced == 2

        config = models_config.get_models_config()
        names = {m.name for m in config.models}
        assert names == {
            f"{COPILOT_MODEL_NAME_PREFIX}claude-sonnet-5",
            f"{COPILOT_MODEL_NAME_PREFIX}gpt-5.5",
        }

        sonnet = models_config.get_model_by_name("copilot:claude-sonnet-5")
        assert sonnet.provider == "GitHubCopilot"
        assert sonnet.model == "claude-sonnet-5"
        assert sonnet.max_input_tokens == 200_000
        assert sonnet.max_tokens == 64_000

    def test_idempotent_resync_updates_in_place(self, copilot_auth, models_config, monkeypatch):
        self._stub_connected(copilot_auth, monkeypatch)
        monkeypatch.setattr(copilot_auth, "list_copilot_models", lambda: [
            {"id": "gpt-5.5", "capabilities": {"limits": {
                "max_context_window_tokens": 400_000, "max_output_tokens": 128_000,
            }}},
        ])
        copilot_auth.sync_copilot_models()

        # Copilot bumps the window on a re-sync -- must update, not duplicate.
        monkeypatch.setattr(copilot_auth, "list_copilot_models", lambda: [
            {"id": "gpt-5.5", "capabilities": {"limits": {
                "max_context_window_tokens": 500_000, "max_output_tokens": 128_000,
            }}},
        ])
        copilot_auth.sync_copilot_models()

        config = models_config.get_models_config()
        matching = [m for m in config.models if m.name == "copilot:gpt-5.5"]
        assert len(matching) == 1
        assert matching[0].max_input_tokens == 500_000

    def test_skips_models_with_disabled_policy(self, copilot_auth, models_config, monkeypatch):
        self._stub_connected(copilot_auth, monkeypatch)
        monkeypatch.setattr(copilot_auth, "list_copilot_models", lambda: [
            {"id": "gpt-5.5", "capabilities": {"limits": {}}},
            {
                "id": "gated-model",
                "capabilities": {"limits": {}},
                "policy": {"state": "disabled"},
            },
        ])
        synced = copilot_auth.sync_copilot_models()
        assert synced == 1
        names = {m.name for m in models_config.get_models_config().models}
        assert "copilot:gated-model" not in names

    def test_missing_limits_gracefully_omitted(self, copilot_auth, models_config, monkeypatch):
        self._stub_connected(copilot_auth, monkeypatch)
        monkeypatch.setattr(copilot_auth, "list_copilot_models", lambda: [
            {"id": "mystery-model", "capabilities": {}},
        ])
        synced = copilot_auth.sync_copilot_models()
        assert synced == 1
        model = models_config.get_model_by_name("copilot:mystery-model")
        assert model.max_input_tokens is None
        assert model.max_tokens is None


# ---------------------------------------------------------------------------
# create_llm_from_config GitHubCopilot branch
# ---------------------------------------------------------------------------

class TestCreateLlmFromConfig:
    def test_builds_chat_openai_with_copilot_base_url_and_headers(self, monkeypatch):
        import clanker.config.copilot_auth as ca
        from clanker.config.models import ModelConfig, create_llm_from_config

        monkeypatch.setattr(ca, "get_valid_copilot_token", lambda: "fake-bearer-token")

        model_config = ModelConfig(
            name="copilot:claude-sonnet-5",
            provider="GitHubCopilot",
            model="claude-sonnet-5",
            max_input_tokens=200_000,
            max_tokens=64_000,
        )
        llm = create_llm_from_config(model_config)

        assert llm.openai_api_base == ca.COPILOT_BASE_URL
        assert llm.model_name == "claude-sonnet-5"
        assert llm.default_headers.get("Copilot-Integration-Id") == "vscode-chat"
        assert llm.max_tokens == 64_000
        assert llm.profile == {"max_input_tokens": 200_000}

    def test_raises_clear_error_when_not_connected(self, monkeypatch, tmp_path):
        import clanker.config.copilot_auth as ca
        from clanker.config.models import ModelConfig, create_llm_from_config

        monkeypatch.setattr(ca, "COPILOT_TOKEN_PATH", tmp_path / "copilot_auth.json")

        model_config = ModelConfig(
            name="copilot:claude-sonnet-5", provider="GitHubCopilot", model="claude-sonnet-5",
        )
        with pytest.raises(CopilotAuthError):
            create_llm_from_config(model_config)


# ---------------------------------------------------------------------------
# Web routes
# ---------------------------------------------------------------------------

class TestCopilotWebRoutes:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from clanker.config.web.app import create_app

        return TestClient(create_app())

    def test_status_disconnected_by_default(self, client, monkeypatch):
        import clanker.config.web.routes as routes_mod

        monkeypatch.setattr(routes_mod, "is_copilot_connected", lambda: False)
        response = client.get("/api/copilot/status")
        assert response.status_code == 200
        assert response.json() == {"connected": False}

    def test_login_start_returns_session(self, client, monkeypatch):
        import clanker.config.web.routes as routes_mod

        monkeypatch.setattr(routes_mod, "start_device_flow", lambda: DeviceFlowSession(
            device_code="dc", user_code="ABCD-1234",
            verification_uri="https://github.com/login/device",
            interval=5, expires_at=time.time() + 900,
        ))
        response = client.post("/api/copilot/login/start")
        assert response.status_code == 200
        body = response.json()
        assert body["user_code"] == "ABCD-1234"
        assert "session_id" in body

    def test_login_poll_unknown_session(self, client):
        response = client.post("/api/copilot/login/poll", json={"session_id": "nope"})
        assert response.status_code == 200
        assert response.json()["status"] == "error"

    def test_login_poll_pending_then_success(self, client, monkeypatch):
        import clanker.config.web.routes as routes_mod

        monkeypatch.setattr(routes_mod, "start_device_flow", lambda: DeviceFlowSession(
            device_code="dc", user_code="ABCD-1234",
            verification_uri="https://github.com/login/device",
            interval=5, expires_at=time.time() + 900,
        ))
        start = client.post("/api/copilot/login/start").json()

        monkeypatch.setattr(routes_mod, "poll_for_github_token", lambda session: None)
        pending = client.post("/api/copilot/login/poll", json={"session_id": start["session_id"]})
        assert pending.json()["status"] == "pending"

        monkeypatch.setattr(routes_mod, "poll_for_github_token", lambda session: "gh_token")
        monkeypatch.setattr(routes_mod, "complete_login", lambda token: None)
        monkeypatch.setattr(routes_mod, "sync_copilot_models", lambda: 3)
        success = client.post("/api/copilot/login/poll", json={"session_id": start["session_id"]})
        assert success.json() == {"status": "success", "models_synced": 3, "detail": None}

        # The session is consumed -- polling again with the same id is now unknown.
        again = client.post("/api/copilot/login/poll", json={"session_id": start["session_id"]})
        assert again.json()["status"] == "error"

    def test_refresh_models_endpoint(self, client, monkeypatch):
        import clanker.config.web.routes as routes_mod

        monkeypatch.setattr(routes_mod, "sync_copilot_models", lambda: 5)
        response = client.post("/api/copilot/refresh-models")
        assert response.status_code == 200
        assert response.json() == {"models_synced": 5}

    def test_refresh_models_surfaces_auth_error(self, client, monkeypatch):
        import clanker.config.web.routes as routes_mod

        def boom():
            raise CopilotAuthError("not connected")

        monkeypatch.setattr(routes_mod, "sync_copilot_models", boom)
        response = client.post("/api/copilot/refresh-models")
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# /copilot-login slash command (in-session REPL command)
# ---------------------------------------------------------------------------

class TestCopilotLoginSlashCommand:
    @pytest.fixture
    def console(self):
        from clanker.ui.console import Console

        return Console()

    @pytest.fixture
    def session_manager(self):
        from clanker.memory.checkpointer import SessionManager

        # Avoid full init side effects (disk I/O) -- handle_command only
        # needs the object identity, not its state, for this command.
        return SessionManager.__new__(SessionManager)

    def test_full_flow_success(self, console, session_manager, monkeypatch):
        import clanker.cli as cli_mod

        session = DeviceFlowSession(
            device_code="dc", user_code="ABCD-1234",
            verification_uri="https://github.com/login/device",
            interval=0, expires_at=time.time() + 900,
        )
        monkeypatch.setattr("clanker.config.copilot_auth.start_device_flow", lambda: session)
        monkeypatch.setattr("clanker.config.copilot_auth.poll_for_github_token", lambda s: "gh_token")
        complete_calls = []
        monkeypatch.setattr(
            "clanker.config.copilot_auth.complete_login",
            lambda token: complete_calls.append(token),
        )
        monkeypatch.setattr("clanker.config.copilot_auth.sync_copilot_models", lambda: 4)
        monkeypatch.setattr(cli_mod.time, "sleep", lambda s: None)

        result = cli_mod.handle_command("/copilot-login", console, session_manager)
        assert result is None
        assert complete_calls == ["gh_token"]

    def test_start_failure_reported_not_raised(self, console, session_manager, monkeypatch):
        import clanker.cli as cli_mod

        def boom():
            raise CopilotAuthError("network is down")

        monkeypatch.setattr("clanker.config.copilot_auth.start_device_flow", boom)
        # Must not raise -- handle_command reports the error and returns.
        result = cli_mod.handle_command("/copilot-login", console, session_manager)
        assert result is None

    def test_keyboard_interrupt_during_poll_is_handled(self, console, session_manager, monkeypatch):
        import clanker.cli as cli_mod

        session = DeviceFlowSession(
            device_code="dc", user_code="ABCD-1234",
            verification_uri="https://github.com/login/device",
            interval=0, expires_at=time.time() + 900,
        )
        monkeypatch.setattr("clanker.config.copilot_auth.start_device_flow", lambda: session)

        def raise_interrupt(s):
            raise KeyboardInterrupt

        monkeypatch.setattr("clanker.config.copilot_auth.poll_for_github_token", raise_interrupt)
        monkeypatch.setattr(cli_mod.time, "sleep", lambda s: None)

        # Cancelling mid-poll must not propagate or crash the REPL.
        result = cli_mod.handle_command("/copilot-login", console, session_manager)
        assert result is None

    def test_listed_in_completer_and_help(self):
        from clanker.cli import CommandCompleter

        assert "/copilot-login" in CommandCompleter.COMMANDS

