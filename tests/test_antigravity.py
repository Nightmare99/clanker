"""Native Google login and Cloud Code integration; no real account required."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from clanker.agent import antigravity as adapter
from clanker.cli import main
from clanker.config import antigravity_auth as auth
from clanker.config import models as model_module
from clanker.config.web.app import create_app


@pytest.fixture(autouse=True)
def isolated_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "TOKEN_PATH", tmp_path / "antigravity_auth.json")
    monkeypatch.setattr(model_module, "MODELS_CONFIG_PATH", tmp_path / "models.json")


def cache_credentials(**overrides):
    auth._save_cache(
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_at": time.time() + 3600,
            "project_id": "project",
            "email": "user@example.com",
            **overrides,
        }
    )


def test_cache_is_private_and_disconnect_keeps_models():
    cache_credentials()
    model_module.add_model(model_module.ModelConfig(name="mine", provider="OpenAI"))
    assert auth.connection_status() == {"connected": True, "email": "user@example.com"}
    if os.name != "nt":
        assert auth.TOKEN_PATH.stat().st_mode & 0o777 == 0o600
    auth.disconnect()
    assert not auth.connection_status()["connected"]
    assert model_module.get_model_by_name("mine")


def test_corrupt_cache_is_disconnected():
    auth.TOKEN_PATH.write_text("[]")
    assert not auth.connection_status()["connected"]
    with pytest.raises(auth.AntigravityAuthError, match="antigravity-login"):
        auth.get_credentials()


def test_unwritable_cache_fails_cleanly_without_replacing_previous_login(monkeypatch):
    cache_credentials()
    previous = auth.TOKEN_PATH.read_bytes()

    def fail_replace(*args):
        raise PermissionError("denied")

    monkeypatch.setattr(auth.os, "replace", fail_replace)
    with pytest.raises(auth.AntigravityAuthError, match="write permissions"):
        auth._save_cache({"access_token": "DO_NOT_EXPOSE"})
    assert auth.TOKEN_PATH.read_bytes() == previous
    assert not list(auth.TOKEN_PATH.parent.glob(".antigravity-*"))


def test_refresh_is_lazy_and_updates_rotated_token(monkeypatch):
    cache_credentials(expires_at=0)
    calls = []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        return 200, {"access_token": "new", "refresh_token": "rotated", "expires_in": 3600}

    monkeypatch.setattr(auth, "_request", request)
    assert auth.get_credentials()["access_token"] == "new"
    assert auth.get_credentials()["access_token"] == "new"
    assert len(calls) == 1
    assert calls[0][1]["form"]["grant_type"] == "refresh_token"
    assert auth._load_cache()["refresh_token"] == "rotated"


@pytest.mark.parametrize(
    "status,error,cleared", [(400, "invalid_grant", True), (503, "unavailable", False)]
)
def test_refresh_failure_preserves_only_retryable_credentials(monkeypatch, status, error, cleared):
    cache_credentials(expires_at=0)
    monkeypatch.setattr(
        auth,
        "_request",
        lambda *a, **k: (status, {"error": error, "access_token": "DO_NOT_EXPOSE"}),
    )
    with pytest.raises(auth.AntigravityAuthError) as exception:
        auth.get_credentials()
    assert "DO_NOT_EXPOSE" not in str(exception.value)
    assert auth.connection_status()["connected"] != cleared


def test_complete_login_exchanges_code_with_matching_redirect_and_pkce(monkeypatch):
    calls = []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        if url == auth.TOKEN_URL:
            return 200, {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}
        if "userinfo" in url:
            return 200, {"email": "user@example.com"}
        return 200, {"cloudaicompanionProject": {"id": "project"}}

    monkeypatch.setattr(auth, "_request", request)
    auth.complete_login("code", "verifier", "http://localhost:51122/oauth-callback")
    assert calls[0][1]["form"]["redirect_uri"] == "http://localhost:51122/oauth-callback"
    assert calls[0][1]["form"]["code_verifier"] == "verifier"
    assert auth.get_credentials()["project_id"] == "project"
    assert "access" not in json.dumps(auth.connection_status())


def test_new_account_onboarding_and_cancel_before_persistence(monkeypatch):
    session = auth.LoginSession(error="cancelled")
    replies = iter(
        [
            (200, {"access_token": "access", "refresh_token": "refresh"}),
            (200, {"email": "user@example.com"}),
            (200, {"allowedTiers": [{"id": "free", "isDefault": True}]}),
            (200, {"done": True, "response": {"cloudaicompanionProject": {"id": "provisioned"}}}),
        ]
    )
    monkeypatch.setattr(auth, "_request", lambda *a, **k: next(replies))
    with pytest.raises(auth.AntigravityAuthError, match="cancelled"):
        auth.complete_login("code", "verifier", "redirect", session=session)
    assert not auth.TOKEN_PATH.exists()


def test_api_fallback_does_not_bypass_denials(monkeypatch):
    calls = []

    def request(url, **kwargs):
        calls.append(url)
        return (503, {}) if len(calls) == 1 else (200, {"ok": True})

    monkeypatch.setattr(auth, "_request", request)
    data, endpoint = auth.api_request("loadCodeAssist", {}, token="token")
    assert data == {"ok": True} and endpoint == auth.ENDPOINTS[1]
    calls.clear()

    def denied(url, **kwargs):
        calls.append(url)
        return 403, {}

    monkeypatch.setattr(auth, "_request", denied)
    with pytest.raises(auth.AntigravityAuthError, match="denied"):
        auth.api_request("loadCodeAssist", {}, token="token")
    assert len(calls) == 1


def test_real_callback_server_validates_state_pkce_and_releases_port(monkeypatch):
    calls = []
    monkeypatch.setattr(auth, "complete_login", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(auth, "sync_models", lambda: 2)
    session = auth.start_login()
    port = session.server.server_port
    try:
        query = parse_qs(urlsplit(session.url).query)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(session.verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        assert query["code_challenge"] == [challenge]
        assert query["redirect_uri"] == [session.redirect_uri]
        assert session.server.server_address[0] == "127.0.0.1"
        with httpx.Client(trust_env=False) as client:
            url = f"http://127.0.0.1:{port}/oauth-callback?"
            assert (
                client.get(url + urlencode({"state": "wrong", "code": "code"})).status_code == 400
            )
            assert auth.poll_login(session) is None
            response = client.get(url + urlencode({"state": session.state, "code": "code"}))
            assert response.status_code == 200
            assert "code" not in response.text
        assert auth.poll_login(session) == 2
        assert auth.poll_login(session) == 2
        assert calls == [("code", session.verifier, session.redirect_uri)]
        assert session.server is None
    finally:
        session.close()


@pytest.mark.parametrize("denied", [False, True])
def test_cancel_and_denial_never_complete_login(denied):
    session = auth.start_login()
    try:
        if denied:
            auth.submit_callback(
                session,
                "http://localhost/oauth-callback?"
                + urlencode({"state": session.state, "error": "access_denied"}),
            )
        else:
            session.cancel()
        with pytest.raises(auth.AntigravityAuthError, match="denied|cancelled"):
            auth.poll_login(session)
        assert not auth.TOKEN_PATH.exists()
    finally:
        session.close()


def test_expired_login_cannot_be_completed():
    session = auth.LoginSession(expires_at=0)
    with pytest.raises(auth.AntigravityAuthError, match="expired"):
        auth.poll_login(session)
    with pytest.raises(auth.AntigravityAuthError, match="no longer"):
        auth.submit_callback(
            session, "http://localhost/?" + urlencode({"state": session.state, "code": "code"})
        )


def test_sync_discovers_models_preserves_custom_settings_and_never_stores_tokens(monkeypatch):
    cache_credentials()
    model_module.add_model(
        model_module.ModelConfig(name="custom", provider="OpenAI", max_tokens=123)
    )
    model_module.add_model(
        model_module.ModelConfig(
            name="antigravity:claude-test",
            provider="Antigravity",
            model="claude-test",
            max_input_tokens=99,
            thinking_budget_tokens=777,
        )
    )
    monkeypatch.setattr(
        auth,
        "api_request",
        lambda *a, **k: (
            {
                "models": {
                    "claude-test": {"maxOutputTokens": 8192},
                    "gemini-test": {"inputTokenLimit": 200000},
                    "gemini-image": {},
                    "unknown-model": {},
                }
            },
            auth.ENDPOINTS[0],
        ),
    )
    assert auth.sync_models() == auth.sync_models() == 2
    config = model_module.get_models_config()
    assert len(config.models) == 3 and config.default == "custom"
    claude = model_module.get_model_by_name("antigravity:claude-test")
    assert claude.max_input_tokens == 99 and claude.thinking_budget_tokens == 777
    assert claude.max_tokens == 8192
    assert "access_token" not in model_module.MODELS_CONFIG_PATH.read_text()


def test_create_provider_and_clear_missing_auth_error():
    config = model_module.ModelConfig(
        name="antigravity:test",
        provider="Antigravity",
        model="claude-test",
        max_input_tokens=200000,
    )
    with pytest.raises(auth.AntigravityAuthError, match="antigravity-login"):
        model_module.create_llm_from_config(config)
    cache_credentials()
    model = model_module.create_llm_from_config(config)
    assert isinstance(model, adapter.ChatAntigravity)
    assert model.profile["max_input_tokens"] == 200000


@pytest.mark.parametrize(
    "model_id,expected",
    [
        ("gemini-3.8-flash-tiered", 1_048_576),
        ("gemini-3.6-flash-high", 1_048_576),
        ("claude-sonnet-4-6", 200_000),
        ("claude-sonnet-4-6-thinking", 200_000),
        ("claude-opus-4-6-thinking", 200_000),
        ("gemini-future", None),
    ],
)
def test_existing_configs_receive_only_documented_context_defaults(model_id, expected):
    # Simulate models.json written by the original login, without token limits.
    model_module.MODELS_CONFIG_PATH.write_text(
        json.dumps({"models": [{"name": "native", "provider": "Antigravity", "model": model_id}]})
    )
    config = model_module.get_model_by_name("native")
    assert config.max_input_tokens == expected
    cache_credentials()
    model = model_module.create_llm_from_config(config)
    assert model.profile.get("max_input_tokens") == expected


def test_discovery_defaults_preserve_manual_limits_and_accept_reported_limits(monkeypatch):
    cache_credentials()
    model_id = "gemini-3.8-flash-tiered"
    metadata = {}
    monkeypatch.setattr(
        auth,
        "api_request",
        lambda *a, **k: ({"models": {model_id: metadata}}, auth.ENDPOINTS[0]),
    )
    assert auth.sync_models() == 1
    name = f"antigravity:{model_id}"
    config = model_module.get_model_by_name(name)
    assert config.max_input_tokens == 1_048_576
    config.max_input_tokens = 123_456
    model_module.add_model(config)
    auth.sync_models()
    assert model_module.get_model_by_name(name).max_input_tokens == 123_456
    metadata["inputTokenLimit"] = 234_567
    auth.sync_models()
    assert model_module.get_model_by_name(name).max_input_tokens == 234_567


@tool
def example_tool(query: str, count: int | None = None) -> str:
    """Find something by query."""
    return query


def test_native_request_tools_images_and_thinking():
    model = adapter.ChatAntigravity(model="claude-test-thinking", thinking_budget_tokens=10000)
    bound = model.bind_tools([example_tool])
    payload = model._payload(
        [
            SystemMessage("Be helpful."),
            HumanMessage(
                content=[
                    {"type": "text", "text": "Look at this"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,YWJj"}},
                ]
            ),
        ],
        {"project_id": "project"},
        None,
        **bound.kwargs,
    )
    request = payload["request"]
    assert request["systemInstruction"]["parts"] == [{"text": "Be helpful."}]
    assert request["contents"][0]["parts"][1] == {
        "inlineData": {"mimeType": "image/png", "data": "YWJj"}
    }
    schema = request["tools"][0]["functionDeclarations"][0]["parameters"]
    assert schema["properties"]["count"] == {"type": "INTEGER", "nullable": True}
    assert request["generationConfig"]["maxOutputTokens"] > 10000
    assert payload["model"] == "claude-test-thinking"


def sse(parts, *, finish="STOP", usage=None):
    response = {"candidates": [{"content": {"parts": parts}, "finishReason": finish}]}
    if usage:
        response["usageMetadata"] = usage
    return "data: " + json.dumps({"response": response}) + "\n\n"


@pytest.fixture
def mock_stream(monkeypatch):
    # Exercise real httpx sync and async streaming + LangChain aggregation.
    original_sync, original_async = httpx.Client, httpx.AsyncClient
    requests = []
    bodies = []

    def handler(request):
        requests.append(request)
        body = bodies.pop(0)
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    # Isolate adapter constructors; SDKs imported by the graph subclass httpx.Client.
    monkeypatch.setattr(
        adapter,
        "httpx",
        SimpleNamespace(
            Client=lambda **kw: original_sync(transport=transport, **kw),
            AsyncClient=lambda **kw: original_async(transport=transport, **kw),
            Timeout=httpx.Timeout,
            HTTPError=httpx.HTTPError,
        ),
    )
    cache_credentials()
    return requests, bodies


@pytest.mark.parametrize("model_id", ["gemini-3.8-flash-tiered", "gemini-future"])
@pytest.mark.parametrize("async_graph", [False, True])
async def test_clanker_default_graph_handles_discovered_models_without_limits(
    mock_stream, model_id, async_graph
):
    from clanker.agent.graph import create_agent_graph, create_agent_graph_async
    from clanker.config.settings import Settings

    requests, bodies = mock_stream
    bodies.append(sse([{"text": "Hello!"}]))
    model_module.add_model(
        model_module.ModelConfig(name="native", provider="Antigravity", model=model_id)
    )
    kwargs = {"settings": Settings(), "model_name": "native", "tools": [], "system_prompt": "Be concise."}
    if async_graph:
        agent, _ = await create_agent_graph_async(**kwargs)
        result = await agent.ainvoke({"messages": [HumanMessage("hi")]})
    else:
        agent = create_agent_graph(**kwargs)
        result = agent.invoke({"messages": [HumanMessage("hi")]})
    assert result["messages"][-1].text == "Hello!"
    assert json.loads(requests[0].content)["model"] == model_id
    assert len(requests) == 1


def test_complete_tool_round_trip_preserves_signatures_and_usage(mock_stream):
    requests, bodies = mock_stream
    bodies.append(
        sse([{"text": "Thinking", "thought": True}, {"thoughtSignature": "thought-signature"}])
        + sse(
            [
                {
                    "functionCall": {
                        "id": "call-1",
                        "name": "example_tool",
                        "args": {"query": "q"},
                    },
                    "thoughtSignature": "call-signature",
                }
            ],
            usage={
                "promptTokenCount": 100,
                "candidatesTokenCount": 10,
                "thoughtsTokenCount": 5,
                "cachedContentTokenCount": 50,
            },
        )
    )
    model = adapter.ChatAntigravity(model="gemini-test")
    bound = model.bind_tools([example_tool])
    response = bound.invoke([HumanMessage("Find q")])
    assert response.tool_calls == [
        {"name": "example_tool", "args": {"query": "q"}, "id": "call-1", "type": "tool_call"}
    ]
    assert response.response_metadata["model_name"] == "gemini-test"
    assert response.usage_metadata["total_tokens"] == 115
    assert response.usage_metadata["input_token_details"]["cache_read"] == 50
    bodies.append(sse([{"text": "Done"}]))
    cache_credentials(access_token="refreshed")
    result = bound.invoke(
        [HumanMessage("Find q"), response, ToolMessage("found", tool_call_id="call-1")]
    )
    payload = json.loads(requests[-1].content)
    assistant = payload["request"]["contents"][1]["parts"]
    assert assistant[0]["thoughtSignature"] == "thought-signature"
    assert assistant[1]["thoughtSignature"] == "call-signature"
    assert (
        payload["request"]["contents"][2]["parts"][0]["functionResponse"]["name"] == "example_tool"
    )
    assert requests[-1].headers["authorization"] == "Bearer refreshed"
    assert result.content[0]["text"] == "Done"


async def test_async_stream_supports_real_langchain_events(mock_stream):
    requests, bodies = mock_stream
    bodies.append(sse([{"text": "Hello "}], finish=None) + sse([{"text": "world"}]))
    model = adapter.ChatAntigravity(model="gemini-test")
    events = [event async for event in model.astream_events([HumanMessage("hello")], version="v2")]
    assert any(event["event"] == "on_chat_model_stream" for event in events)
    end = next(event for event in events if event["event"] == "on_chat_model_end")
    assert end["data"]["output"].content[0]["text"] == "Hello world"
    assert len(requests) == 1


def test_switching_models_drops_opaque_signatures_and_tool_name_mapping():
    previous = AIMessage(
        content=[{"type": "thinking", "thinking": "reason", "signature": "old"}],
        tool_calls=[{"id": "call", "name": "mcp.search", "args": {}}],
        additional_kwargs={"antigravity_signatures": {"call": "old"}},
        response_metadata={"model_name": "claude-old"},
    )
    contents, _ = adapter._contents(
        [HumanMessage("go"), previous, ToolMessage("result", tool_call_id="call")], "gemini-new"
    )
    assert contents[1]["parts"] == [
        {
            "functionCall": {"id": "call", "name": "mcp_search", "args": {}},
            "thoughtSignature": "skip_thought_signature_validator",
        }
    ]
    decoder = adapter._Decoder("gemini-new", {"mcp_search": "mcp.search"})
    chunks = list(
        decoder.decode(
            {
                "candidates": [
                    {"content": {"parts": [{"functionCall": {"name": "mcp_search", "args": {}}}]}}
                ]
            }
        )
    )
    assert chunks[0].message.tool_calls[0]["name"] == "mcp.search"


@pytest.mark.parametrize(
    "body,match",
    [
        ("data: invalid\n\n", "invalid"),
        (sse([], finish=None), "empty or incomplete"),
        ('data: {"error":{"message":"private-body"}}\n\n', "streaming API error"),
    ],
)
def test_broken_streams_fail_without_echoing_response_bodies(mock_stream, body, match):
    _, bodies = mock_stream
    bodies.append(body)
    with pytest.raises(auth.AntigravityAuthError, match=match) as exc:
        adapter.ChatAntigravity(model="gemini-test").invoke("go")
    assert "private-body" not in str(exc.value)


def test_parallel_tool_results_keep_images_after_responses():
    messages = [
        AIMessage(
            "",
            tool_calls=[
                {"id": "1", "name": "read", "args": {}},
                {"id": "2", "name": "read", "args": {}},
            ],
        ),
        ToolMessage(
            content=[
                {"type": "text", "text": "a"},
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": "a"},
                },
            ],
            tool_call_id="1",
        ),
        ToolMessage("b", tool_call_id="2"),
    ]
    contents, _ = adapter._contents(messages, "claude-test")
    assert [next(iter(part)) for part in contents[1]["parts"]] == [
        "functionResponse",
        "functionResponse",
        "inlineData",
    ]


def test_web_login_cancel_and_manual_callback_are_wired(monkeypatch):
    sessions = []

    def start():
        session = auth.LoginSession(url="https://accounts.google.com/login")
        sessions.append(session)
        return session

    monkeypatch.setattr(auth, "start_login", start)
    monkeypatch.setattr(auth, "complete_login", lambda *a, **k: cache_credentials())
    monkeypatch.setattr(auth, "sync_models", lambda: 2)
    client = TestClient(create_app())
    start = client.post("/api/antigravity/login/start").json()
    assert start["authorization_url"].startswith("https://accounts.google.com")
    request = {"session_id": start["session_id"]}
    assert client.post("/api/antigravity/login/poll", json=request).json()["status"] == "pending"
    request["callback_url"] = "http://localhost/?" + urlencode(
        {"state": sessions[0].state, "code": "code"}
    )
    response = client.post("/api/antigravity/login/poll", json=request)
    assert response.json()["models_synced"] == 2
    assert "access_token" not in response.text
    assert client.get("/api/antigravity/status").json()["connected"]
    start = client.post("/api/antigravity/login/start").json()
    request = {"session_id": start["session_id"]}
    assert client.post("/api/antigravity/login/cancel", json=request).json()["success"]
    assert sessions[-1].error
    assert client.post("/api/antigravity/login/poll", json=request).json()["status"] == "error"
    assert client.post("/api/antigravity/refresh-models").json()["models_synced"] == 2
    assert client.post("/api/antigravity/disconnect").json()["success"]
    assert not client.get("/api/antigravity/status").json()["connected"]


def test_cli_help_and_login_dispatch(monkeypatch):
    import clanker.cli as cli

    calls = []
    monkeypatch.setattr(
        cli, "_run_antigravity_login", lambda emit, **kwargs: calls.append(kwargs) or 3
    )
    runner = CliRunner()
    result = runner.invoke(main, ["antigravity-login", "--help"])
    assert result.exit_code == 0 and "Google" in result.output and not calls
    result = runner.invoke(main, ["antigravity-login", "--no-browser", "--manual"])
    assert result.exit_code == 0 and "Synced 3" in result.output
    assert calls == [{"no_browser": True, "manual": True}]


def test_slash_command_and_completion(monkeypatch):
    import clanker.cli as cli
    from clanker.ui.app import _SLASH_COMMANDS
    from clanker.ui.console import Console

    calls = []
    monkeypatch.setattr(cli, "_run_antigravity_login", lambda emit: calls.append(True) or 2)
    assert cli.handle_command("/antigravity-login", Console(), None) is None
    assert calls == [True]
    assert "/antigravity-login" in _SLASH_COMMANDS


def test_real_agent_executes_a_tool_and_replays_its_signature(mock_stream):
    from langchain.agents import create_agent

    requests, bodies = mock_stream
    bodies.extend(
        [
            sse(
                [
                    {
                        "functionCall": {
                            "id": "one",
                            "name": "example_tool",
                            "args": {"query": "found"},
                        },
                        "thoughtSignature": "signature",
                    }
                ]
            ),
            sse([{"text": "Finished"}]),
        ]
    )
    agent = create_agent(adapter.ChatAntigravity(model="gemini-test"), [example_tool])
    output = agent.invoke({"messages": [HumanMessage("Find something")]})
    assert output["messages"][-1].content[0]["text"] == "Finished"
    assert any(
        isinstance(message, ToolMessage) and message.content == "found"
        for message in output["messages"]
    )
    assistant_parts = json.loads(requests[1].content)["request"]["contents"][1]["parts"]
    assert assistant_parts[0]["thoughtSignature"] == "signature"


def test_signed_parts_are_not_merged_with_later_unsigned_parts(mock_stream):
    _, bodies = mock_stream
    bodies.append(
        sse([{"text": "signed", "thoughtSignature": "signature"}], finish=None)
        + sse([{"text": "unsigned"}])
    )
    message = adapter.ChatAntigravity(model="gemini-test").invoke("go")
    assert len(message.content) == 2
    parts = adapter._parts(message.content, assistant=True)
    assert parts == [{"text": "signed", "thoughtSignature": "signature"}, {"text": "unsigned"}]


async def test_tui_login_stays_responsive_and_ctrl_c_cleans_up(monkeypatch):
    from clanker.ui.app import ClankerApp

    session = auth.LoginSession(url="https://accounts.google.com/login")
    started = threading.Event()
    monkeypatch.setattr(auth, "start_login", lambda: session)

    def poll(current):
        started.set()
        return None

    monkeypatch.setattr(auth, "poll_login", poll)
    monkeypatch.setattr("webbrowser.open", lambda url: True)
    monkeypatch.setattr("clanker.ui.streaming._cancel_streaming_task", lambda: None)
    log = MagicMock()
    event = threading.Event()
    app = SimpleNamespace(
        get_chat_log=lambda: log,
        reset_interrupt=event.clear,
        _interrupt_event=event,
        _subagent_runs=[],
        interrupt_requested=False,
    )
    task = asyncio.create_task(ClankerApp._antigravity_login_flow(app))
    for _ in range(50):
        if started.is_set():
            break
        await asyncio.sleep(0.01)
    assert started.is_set() and not task.done()
    ClankerApp.action_interrupt(app)
    await asyncio.wait_for(task, timeout=2)
    assert session.error and app._antigravity_login_session is None
    assert any("cancelled" in call.args[0] for call in log.add_message.call_args_list)


def test_existing_transcript_tool_output_is_usable_without_call_ids():
    contents, _ = adapter._contents(
        [HumanMessage("old task"), AIMessage("done"), ToolMessage("old output", tool_call_id="")],
        "claude-test",
    )
    assert contents[-1] == {"role": "user", "parts": [{"text": "old output"}]}
