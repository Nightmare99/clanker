"""ChatGPT account provider tests; no account credentials or live APIs needed."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import socket
import threading
import time
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from clanker.agent import chatgpt as adapter
from clanker.cli import main
from clanker.config import chatgpt_auth as auth
from clanker.config import models as models
from clanker.config.web.app import create_app


@pytest.fixture(autouse=True)
def isolated_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "TOKEN_PATH", tmp_path / "chatgpt_auth.json")
    monkeypatch.setattr(models, "MODELS_CONFIG_PATH", tmp_path / "models.json")
    monkeypatch.setattr(auth, "_version_cache", (auth.DEFAULT_CODEX_VERSION, time.time() + 3600))


def jwt(claims):
    return (
        "header."
        + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        + ".signature"
    )


def cache_credentials(**overrides):
    auth._save_cache(
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "account_id": "account",
            "email": "user@example.com",
            "expires_at": time.time() + 3600,
            **overrides,
        }
    )


def tokens():
    return {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_in": 3600,
        "id_token": jwt(
            {
                "email": "user@example.com",
                "https://api.openai.com/auth": {"chatgpt_account_id": "account"},
            }
        ),
    }


def callback(session, **query):
    return auth.REDIRECT_URI + "?" + urlencode({"state": session.state, "code": "code", **query})


def test_secure_cache_and_disconnect_keep_model_settings():
    cache_credentials()
    models.add_model(models.ModelConfig(name="native", provider="ChatGPT", model="test"))
    if os.name != "nt":
        assert auth.TOKEN_PATH.stat().st_mode & 0o777 == 0o600
    assert auth.connection_status() == {"connected": True, "email": "user@example.com"}
    assert "access" not in json.dumps(auth.connection_status())
    auth.disconnect()
    assert not auth.connection_status()["connected"]
    assert models.get_model_by_name("native")


def test_cache_write_failure_is_safe_and_atomic(monkeypatch):
    cache_credentials()
    previous = auth.TOKEN_PATH.read_bytes()

    def fail(*args):
        raise PermissionError("denied")

    monkeypatch.setattr(auth.os, "replace", fail)
    with pytest.raises(auth.ChatGPTAuthError, match="write permissions"):
        auth._save_cache({"access_token": "DO_NOT_EXPOSE"})
    assert auth.TOKEN_PATH.read_bytes() == previous
    assert not list(auth.TOKEN_PATH.parent.glob(".chatgpt-*"))


@pytest.mark.parametrize("contents", ["[]", "not JSON", "{}"])
def test_missing_and_corrupt_credentials_give_login_command(contents):
    auth.TOKEN_PATH.write_text(contents)
    assert not auth.connection_status()["connected"]
    with pytest.raises(auth.ChatGPTAuthError, match="openai-login"):
        auth.get_credentials()


def test_refresh_rotates_tokens_without_losing_catalogue(monkeypatch):
    cache_credentials(expires_at=0, models={"test": {"use_responses_lite": True}})
    calls = []
    monkeypatch.setattr(
        auth,
        "_request",
        lambda *a, **k: (
            calls.append(k)
            or (
                200,
                {
                    "access_token": "new",
                    "refresh_token": "rotated",
                    "expires_in": 3600,
                },
            )
        ),
    )
    assert auth.get_credentials()["access_token"] == "new"
    assert auth.get_credentials()["refresh_token"] == "rotated"
    assert len(calls) == 1
    assert calls[0]["body"]["grant_type"] == "refresh_token"
    assert "client_secret" not in calls[0]["body"]
    assert auth.model_info("test")["use_responses_lite"]


@pytest.mark.parametrize(
    "status,error,cleared",
    [(400, "invalid_grant", True), (401, "unauthorized", True), (503, "unavailable", False)],
)
def test_refresh_failure_never_echoes_tokens(monkeypatch, status, error, cleared):
    cache_credentials(expires_at=0)
    monkeypatch.setattr(
        auth,
        "_request",
        lambda *a, **k: (status, {"error": error, "refresh_token": "DO_NOT_EXPOSE"}),
    )
    with pytest.raises(auth.ChatGPTAuthError) as exc:
        auth.get_credentials()
    assert "DO_NOT_EXPOSE" not in str(exc.value)
    assert auth.connection_status()["connected"] is not cleared


def test_manual_login_pkce_and_exchange(monkeypatch):
    calls = []
    monkeypatch.setattr(auth, "_request", lambda *a, **k: calls.append((a, k)) or (200, tokens()))
    monkeypatch.setattr(auth, "sync_models", lambda: 2)
    session = auth.start_login(manual=True)
    try:
        assert not session.servers
        query = parse_qs(urlsplit(session.url).query)
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(session.verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        assert query["code_challenge"] == [expected]
        assert query["redirect_uri"] == [auth.REDIRECT_URI]
        assert query["codex_cli_simplified_flow"] == ["true"]
        assert auth.poll_login(session) is None
        with pytest.raises(auth.ChatGPTAuthError, match="state"):
            auth.submit_callback(session, callback(session, state="wrong"))
        auth.submit_callback(session, callback(session))
        assert auth.poll_login(session) == auth.poll_login(session) == 2
        form = calls[0][1]["form"]
        assert form["code_verifier"] == session.verifier
        assert form["redirect_uri"] == auth.REDIRECT_URI
        assert "client_secret" not in form
        assert auth.get_credentials()["account_id"] == "account"
    finally:
        session.close()


def test_loopback_callback_and_cleanup(monkeypatch):
    monkeypatch.setattr(auth, "_request", lambda *a, **k: (200, tokens()))
    monkeypatch.setattr(auth, "sync_models", lambda: 1)
    try:
        session = auth.start_login()
    except auth.ChatGPTAuthError:
        pytest.skip("OAuth callback port 1455 is occupied by another application")
    try:
        assert all(server.server_address[0] in {"127.0.0.1", "::1"} for server in session.servers)
        with httpx.Client(trust_env=False) as client:
            assert (
                client.get(callback(session).replace("localhost", "127.0.0.1")).status_code == 200
            )
        assert auth.poll_login(session) == 1
        assert not session.servers
    finally:
        session.close()


def test_busy_callback_port_offers_manual_fallback():
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", 1455))
        except OSError:
            pytest.skip("OAuth callback port 1455 already occupied")
        listener.listen()
        with pytest.raises(auth.ChatGPTAuthError, match="--manual"):
            auth.start_login()
        session = auth.start_login(manual=True)
        session.close()


@pytest.mark.parametrize("reason", ["cancel", "denied", "expired", "late_cancel"])
def test_cancel_denial_expiry_and_exchange_races_never_save_tokens(monkeypatch, reason):
    session = auth.start_login(manual=True)
    try:
        if reason == "denied":
            auth.submit_callback(session, callback(session, error="access_denied"))
        elif reason == "expired":
            session.expires_at = 0
        elif reason == "cancel":
            session.cancel()
        else:
            auth.submit_callback(session, callback(session))

            def request(*args, **kwargs):
                session.cancel()
                return 200, tokens()

            monkeypatch.setattr(auth, "_request", request)
        with pytest.raises(auth.ChatGPTAuthError):
            auth.poll_login(session)
        assert not auth.TOKEN_PATH.exists()
    finally:
        session.close()


def test_model_discovery_preserves_defaults_and_uses_catalogue_limits(monkeypatch):
    cache_credentials()
    models.add_model(models.ModelConfig(name="default", provider="OpenAI"))
    models.add_model(
        models.ModelConfig(
            name="chatgpt:test",
            provider="ChatGPT",
            model="test",
            max_input_tokens=123,
            reasoning_effort="high",
        )
    )
    metadata = {"slug": "test", "default_reasoning_level": "low", "use_responses_lite": True}
    catalogue = [
        metadata,
        {"slug": "new", "context_window": 987654},
        {"slug": "hidden", "visibility": "hidden"},
        {"slug": "unsupported", "supported_in_api": False},
        {"slug": "gpt-image-test"},
        None,
    ]
    calls = []
    monkeypatch.setattr(
        auth, "_request", lambda *a, **k: calls.append((a, k)) or (200, {"models": catalogue})
    )
    assert auth.sync_models() == 2
    assert models.get_models_config().default == "default"
    assert models.get_model_by_name("chatgpt:new").max_input_tokens == 987654
    assert models.get_model_by_name("chatgpt:test").max_input_tokens == 123
    assert models.get_model_by_name("chatgpt:test").reasoning_effort == "high"
    assert auth.model_info("test")["use_responses_lite"]
    assert "client_version=" in calls[0][0][0]
    assert calls[0][1]["headers"]["chatgpt-account-id"] == "account"
    metadata["context_window"] = 200000
    auth.sync_models()
    assert models.get_model_by_name("chatgpt:test").max_input_tokens == 200000
    assert "access_token" not in models.MODELS_CONFIG_PATH.read_text()


@pytest.mark.parametrize("status,data", [(401, {}), (200, {}), (200, {"models": []})])
def test_discovery_failure_preserves_saved_models(monkeypatch, status, data):
    cache_credentials()
    models.add_model(models.ModelConfig(name="default", provider="OpenAI"))
    monkeypatch.setattr(auth, "_request", lambda *a, **k: (status, data))
    with pytest.raises(auth.ChatGPTAuthError):
        auth.sync_models()
    assert models.get_models_config().default == "default"


@tool
def example_tool(query: str) -> str:
    """Return the queried value."""
    return query


def sse_response(*, text="Hello!", tool_call=False, reasoning=False):
    events = []
    output = []
    response_id = "resp_" + uuid.uuid4().hex

    def event(kind, **fields):
        events.append({"type": kind, "sequence_number": len(events), **fields})

    event("response.created", response={"id": response_id, "object": "response", "output": []})
    if reasoning:
        item = {
            "type": "reasoning",
            "id": "rs_test",
            "summary": [],
            "encrypted_content": "encrypted-reasoning",
        }
        output.append(item)
        event(
            "response.output_item.added",
            output_index=0,
            item={"type": "reasoning", "id": "rs_test", "summary": []},
        )
        event("response.output_item.done", output_index=0, item=item)
    index = len(output)
    if tool_call:
        item = {
            "type": "function_call",
            "id": "fc_test",
            "call_id": "call_test",
            "name": "example_tool",
            "arguments": '{"query":"found"}',
            "status": "completed",
        }
        output.append(item)
        event("response.output_item.added", output_index=index, item={**item, "arguments": ""})
        event(
            "response.function_call_arguments.delta",
            output_index=index,
            item_id="fc_test",
            delta=item["arguments"],
        )
    else:
        item = {
            "type": "message",
            "id": "msg_test",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }
        output.append(item)
        event(
            "response.output_text.delta",
            output_index=index,
            content_index=0,
            item_id="msg_test",
            delta=text,
        )
        event(
            "response.output_text.done",
            output_index=index,
            content_index=0,
            item_id="msg_test",
            text=text,
        )
    event(
        "response.completed",
        response={
            "id": response_id,
            "object": "response",
            "created_at": 1,
            "model": "test",
            "status": "completed",
            "output": output,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
                "input_tokens_details": {"cached_tokens": 30},
                "output_tokens_details": {"reasoning_tokens": 5},
            },
            "error": None,
        },
    )
    return "".join("event: " + e["type"] + "\ndata: " + json.dumps(e) + "\n\n" for e in events)


@pytest.fixture
def mock_stream(monkeypatch):
    original_sync, original_async = httpx.Client, httpx.AsyncClient
    requests, bodies = [], []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200, text=bodies.pop(0), headers={"content-type": "text/event-stream"}
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        adapter,
        "httpx",
        SimpleNamespace(
            Client=lambda **kw: original_sync(transport=transport, **kw),
            AsyncClient=lambda **kw: original_async(transport=transport, **kw),
            Timeout=httpx.Timeout,
        ),
    )
    cache_credentials()
    return requests, bodies


@pytest.mark.parametrize("async_graph", [False, True])
@pytest.mark.parametrize("lite", [False, True])
async def test_real_clanker_graph_executes_tools_and_replays_reasoning(
    mock_stream, async_graph, lite
):
    from clanker.agent.graph import create_agent_graph, create_agent_graph_async
    from clanker.config.settings import Settings

    requests, bodies = mock_stream
    cache_credentials(
        models={"test": {"use_responses_lite": lite, "default_reasoning_level": "low"}}
    )
    models.add_model(models.ModelConfig(name="native", provider="ChatGPT", model="test"))
    bodies.extend([sse_response(tool_call=True, reasoning=True), sse_response(text="Finished")])
    kwargs = {
        "settings": Settings(),
        "model_name": "native",
        "tools": [example_tool],
        "system_prompt": "Be concise.",
    }
    if async_graph:
        graph, _ = await create_agent_graph_async(**kwargs)
        result = await graph.ainvoke({"messages": [HumanMessage("Find something")]})
    else:
        graph = create_agent_graph(**kwargs)
        result = graph.invoke({"messages": [HumanMessage("Find something")]})
    assert result["messages"][-1].text == "Finished"
    assert any(isinstance(m, ToolMessage) and m.content == "found" for m in result["messages"])
    second = json.loads(requests[1].content)
    assert any(item.get("encrypted_content") == "encrypted-reasoning" for item in second["input"])
    assert any(
        item.get("type") == "function_call_output" and item["call_id"] == "call_test"
        for item in second["input"]
    )
    assert second["store"] is False and second["stream"] is True
    assert "previous_response_id" not in second and "max_output_tokens" not in second
    assert requests[0].headers["authorization"] == "Bearer access"
    assert requests[0].headers["chatgpt-account-id"] == "account"
    assert "responses-lite" in str(requests[0].headers) if lite else "tools" in second
    assert result["messages"][-1].usage_metadata["input_token_details"]["cache_read"] == 30


def test_payload_images_and_explicit_reasoning_effort():
    model = adapter.ChatGPTModel(
        model="test",
        api_key="dummy",
        use_responses_api=True,
        store=False,
        reasoning_effort="high",
        account_model_info={"default_reasoning_level": "low"},
    )
    payload = model._get_request_payload(
        [
            SystemMessage("Be concise."),
            HumanMessage(
                content=[
                    {"type": "text", "text": "Look"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,YQ=="}},
                ]
            ),
        ],
        max_tokens=100,
    )
    assert payload["instructions"] == "Be concise."
    assert payload["reasoning"]["effort"] == "high"
    assert payload["input"][0]["content"][1]["type"] == "input_image"
    assert "max_output_tokens" not in payload


def test_unencrypted_reasoning_from_other_providers_is_not_replayed():
    model = adapter.ChatGPTModel(model="test", api_key="dummy", use_responses_api=True, store=False)
    payload = model._get_request_payload(
        [
            HumanMessage("old task"),
            AIMessage(
                content=[
                    {
                        "type": "reasoning",
                        "id": "old",
                        "summary": [{"type": "summary_text", "text": "old thinking"}],
                    },
                    {"type": "text", "text": "old response"},
                ]
            ),
            HumanMessage("continue"),
        ]
    )
    assert not any(item.get("type") == "reasoning" for item in payload["input"])


@pytest.mark.parametrize("async_stream", [False, True])
async def test_incomplete_stream_reports_error(mock_stream, async_stream):
    _, bodies = mock_stream
    body = sse_response()
    bodies.append(body.split("event: response.completed")[0])
    model = models.create_llm_from_config(
        models.ModelConfig(name="native", provider="ChatGPT", model="test")
    )
    with pytest.raises(auth.ChatGPTAuthError, match="before completion"):
        if async_stream:
            await model.ainvoke("hi")
        else:
            model.invoke("hi")


def test_streaming_context_error_is_recognized_for_compaction(mock_stream):
    from clanker.context import is_context_length_error

    _, bodies = mock_stream
    bodies.append(
        'event: response.failed\ndata: {"type":"response.failed","sequence_number":0,"response":{"id":"resp_error","error":{"code":"context_length_exceeded","message":"too long"}}}\n\n'
    )
    model = models.create_llm_from_config(
        models.ModelConfig(name="native", provider="ChatGPT", model="test")
    )
    with pytest.raises(auth.ChatGPTAuthError) as exc:
        model.invoke("hi")
    assert is_context_length_error(exc.value)


def test_refresh_is_applied_to_each_stream_request(mock_stream, monkeypatch):
    requests, bodies = mock_stream
    config = models.ModelConfig(name="native", provider="ChatGPT", model="test")
    model = models.create_llm_from_config(config)
    bodies.append(sse_response())
    model.invoke("first")
    cache_credentials(expires_at=0)
    monkeypatch.setattr(
        auth, "_request", lambda *a, **k: (200, {"access_token": "new", "expires_in": 3600})
    )
    bodies.append(sse_response())
    model.invoke("second")
    assert requests[1].headers["authorization"] == "Bearer new"


def test_web_account_flow_status_cancel_refresh_disconnect(monkeypatch):
    sessions = []
    original_start = auth.start_login

    def fake_start(**kwargs):
        session = original_start(manual=True)
        sessions.append(session)
        return session

    monkeypatch.setattr(auth, "start_login", fake_start)
    monkeypatch.setattr(auth, "_request", lambda *a, **k: (200, tokens()))
    monkeypatch.setattr(auth, "sync_models", lambda: 2)
    client = TestClient(create_app())
    result = client.post("/api/chatgpt/login/start", json={"manual": True}).json()
    request = {"session_id": result["session_id"]}
    assert client.post("/api/chatgpt/login/poll", json=request).json()["status"] == "pending"
    request["callback_url"] = callback(sessions[-1])
    response = client.post("/api/chatgpt/login/poll", json=request)
    assert response.json()["models_synced"] == 2
    assert "access_token" not in response.text
    assert client.get("/api/chatgpt/status").json()["connected"]
    result = client.post("/api/chatgpt/login/start", json={}).json()
    request = {"session_id": result["session_id"]}
    assert client.post("/api/chatgpt/login/cancel", json=request).json()["success"]
    assert sessions[-1].error
    assert client.post("/api/chatgpt/login/poll", json=request).json()["status"] == "error"
    assert client.post("/api/chatgpt/refresh-models").json()["models_synced"] == 2
    assert client.post("/api/chatgpt/disconnect").json()["success"]
    assert not client.get("/api/chatgpt/status").json()["connected"]


def test_cli_and_slash_command_dispatch(monkeypatch):
    import clanker.cli as cli
    from clanker.ui.app import _SLASH_COMMANDS
    from clanker.ui.console import Console

    calls = []
    monkeypatch.setattr(cli, "_run_openai_login", lambda emit, **kw: calls.append(kw) or 2)
    runner = CliRunner()
    assert runner.invoke(main, ["openai-login", "--help"]).exit_code == 0
    result = runner.invoke(main, ["openai-login", "--no-browser", "--manual"])
    assert result.exit_code == 0 and "Synced 2" in result.output
    assert calls == [{"no_browser": True, "manual": True}]
    assert cli.handle_command("/openai-login", Console(), None) is None
    assert "/openai-login" in _SLASH_COMMANDS


async def test_tui_login_is_responsive_and_cancelled(monkeypatch):
    from clanker.ui.app import ClankerApp

    session = auth.LoginSession(url="https://auth.openai.com/oauth/authorize")
    started = threading.Event()
    monkeypatch.setattr(auth, "start_login", lambda: session)

    def poll(current):
        started.set()
        return None

    monkeypatch.setattr(auth, "poll_login", poll)
    monkeypatch.setattr("webbrowser.open", lambda url: True)
    monkeypatch.setattr("clanker.ui.streaming._cancel_streaming_task", lambda: None)
    log, interrupt = MagicMock(), threading.Event()
    app = SimpleNamespace(
        get_chat_log=lambda: log,
        reset_interrupt=interrupt.clear,
        _interrupt_event=interrupt,
        _subagent_runs=[],
        interrupt_requested=False,
    )
    task = asyncio.create_task(ClankerApp._chatgpt_login_flow(app))
    for _ in range(50):
        if started.is_set():
            break
        await asyncio.sleep(0.01)
    assert started.is_set() and not task.done()
    ClankerApp.action_interrupt(app)
    await asyncio.wait_for(task, timeout=2)
    assert session.error and app._chatgpt_login_session is None
