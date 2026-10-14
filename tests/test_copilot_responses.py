"""Copilot endpoint discovery, overrides, web editing, and Responses tool replay."""

import asyncio
import json
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from clanker.config import copilot_auth
from clanker.config.models import ModelConfig, create_llm_from_config
from clanker.config.settings import Settings
from clanker.config.web.app import create_app
from tests.test_chatgpt import example_tool, sse_response


@pytest.fixture
def models(monkeypatch, tmp_path):
    import clanker.config.models as module

    monkeypatch.setattr(module, "MODELS_CONFIG_PATH", tmp_path / "models.json")
    return module


@pytest.mark.parametrize(
    "model_id,endpoints,expected",
    [
        ("gpt-6.1-sol", None, True),
        ("gpt-5.5", None, True),
        ("gpt-10-agent", None, True),
        ("gpt-4o", None, False),
        ("claude-sonnet-5", None, False),
        ("future-model", ["/responses"], True),
        ("future-model", ["/chat/completions", "/responses"], True),
        ("gpt-6.1-sol", ["/chat/completions"], False),
    ],
)
def test_automatic_routing_uses_capabilities_before_legacy_fallback(model_id, endpoints, expected):
    model = ModelConfig(
        name="test", provider="GitHubCopilot", model=model_id, copilot_supported_endpoints=endpoints
    )
    assert model.uses_copilot_responses_api is expected


@pytest.mark.parametrize(
    "endpoint,legacy_flag,expected",
    [
        ("responses", False, True),
        ("chat-completions", True, False),
        ("auto", True, True),
        ("auto", False, False),
    ],
)
def test_explicit_and_legacy_overrides(endpoint, legacy_flag, expected):
    model = ModelConfig(
        name="test",
        provider="GitHubCopilot",
        model="unknown",
        copilot_api_endpoint=endpoint,
        use_responses_api=legacy_flag,
    )
    assert model.uses_copilot_responses_api is expected


def test_refresh_caches_capabilities_and_preserves_user_settings(models, monkeypatch):
    models.add_model(
        ModelConfig(
            name="copilot:gpt-6.1-sol",
            provider="GitHubCopilot",
            model="gpt-6.1-sol",
            copilot_api_endpoint="responses",
            reasoning_effort="high",
            cost_input=2.0,
        )
    )
    monkeypatch.setattr(
        copilot_auth,
        "list_copilot_models",
        lambda: [
            {
                "id": "gpt-6.1-sol",
                "supported_endpoints": ["/responses"],
                "capabilities": {"limits": {"max_context_window_tokens": 128_000}},
            }
        ],
    )
    assert copilot_auth.sync_copilot_models() == 1
    saved = models.get_model_by_name("copilot:gpt-6.1-sol")
    assert saved.copilot_supported_endpoints == ["/responses"]
    assert saved.copilot_api_endpoint == "responses"
    assert saved.reasoning_effort == "high"
    assert saved.cost_input == 2.0
    assert saved.max_input_tokens == 128_000


def test_web_edit_round_trips_endpoint_and_test_uses_same_factory(models, monkeypatch):

    with TestClient(create_app()) as client:
        name = "copilot:future-model"
        body = {
            "name": name,
            "provider": "GitHubCopilot",
            "model": "future-model",
            "copilot_api_endpoint": "responses",
            "copilot_supported_endpoints": ["/responses"],
        }
        assert client.post("/api/models", json=body).status_code == 200
        assert client.get("/api/models").json()["models"][0]["copilot_api_endpoint"] == "responses"
        # Partial clients must not erase discovered endpoint metadata.
        edit = {
            "name": name,
            "provider": "GitHubCopilot",
            "model": "future-model",
            "copilot_api_endpoint": "chat-completions",
        }
        assert client.put(f"/api/models/{name}", json=edit).status_code == 200
        saved = models.get_model_by_name(name)
        assert saved.copilot_api_endpoint == "chat-completions"
        assert saved.copilot_supported_endpoints == ["/responses"]
        llm = MagicMock()
        factory = MagicMock(return_value=llm)
        monkeypatch.setattr(models, "create_llm_from_config", factory)
        assert client.post(f"/api/models/{name}/test").json()["success"]
        assert factory.call_args.args[0].copilot_api_endpoint == "chat-completions"
        llm.invoke.assert_called_once_with("Say 'ok'")
        edit["copilot_api_endpoint"] = "invalid"
        assert client.put(f"/api/models/{name}", json=edit).status_code == 422
        edit["copilot_api_endpoint"] = "auto"
        edit["model"] = "another-model"
        assert client.put(f"/api/models/{name}", json=edit).status_code == 200
        assert models.get_model_by_name(name).copilot_supported_endpoints is None


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_streamed_tool_round_uses_responses_and_replays_reasoning(
    models, monkeypatch, asynchronous
):
    from clanker.agent.graph import create_agent_graph

    requests = []
    token_provider = MagicMock(side_effect=lambda: f"test-token-{token_provider.call_count}")
    monkeypatch.setattr(copilot_auth, "get_valid_copilot_token", token_provider)

    def respond(request):
        payload = json.loads(request.content)
        requests.append((request, payload))
        assert request.url.path == "/responses"
        data = sse_response(tool_call=len(requests) == 1, reasoning=len(requests) == 1)
        if payload.get("stream"):
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=data)
        completed = json.loads(data.strip().split("data: ")[-1])["response"]
        return httpx.Response(200, json=completed)

    transport = httpx.MockTransport(respond)
    sync_client = httpx.Client(transport=transport)
    async_client = httpx.AsyncClient(transport=transport)
    monkeypatch.setattr(
        models,
        "_fresh_openai_http_clients",
        lambda: {
            "http_client": sync_client,
            "http_async_client": async_client,
        },
    )
    config = ModelConfig(
        name="copilot:gpt-6.1-sol",
        provider="GitHubCopilot",
        model="gpt-6.1-sol",
        max_input_tokens=128_000,
        reasoning_effort="high",
    )
    models.add_model(config)
    checkpoint = MemorySaver()
    graph = create_agent_graph(
        Settings(),
        checkpointer=checkpoint,
        tools=[example_tool],
        model_name=config.name,
        system_prompt="Test",
    )
    state = {"messages": [HumanMessage(content="Look it up")]}
    graph_config = {"configurable": {"thread_id": "responses-test"}}
    try:
        if asynchronous:
            events = [
                event async for event in graph.astream_events(state, graph_config, version="v2")
            ]
        else:
            events = await asyncio.to_thread(
                lambda: list(graph.stream(state, graph_config, stream_mode="messages"))
            )
        assert events
        assert len(requests) == 2
        first_request, first = requests[0]
        second_request, second = requests[1]
        assert first["store"] is False
        assert first["reasoning"]["effort"] == "high"
        assert "reasoning.encrypted_content" in first["include"]
        assert first_request.headers["authorization"] != second_request.headers["authorization"]
        assert "previous_response_id" not in second
        assert any(item.get("type") == "function_call_output" for item in second["input"])
        assert any(
            item.get("type") == "reasoning" and item.get("encrypted_content")
            for item in second["input"]
        )
    finally:
        sync_client.close()
        await async_client.aclose()


def test_factory_honors_override_on_non_gpt_model(monkeypatch):
    monkeypatch.setattr(copilot_auth, "get_valid_copilot_token", lambda: "test-token")
    config = ModelConfig(
        name="test", provider="GitHubCopilot", model="future-model", use_responses_api=True
    )
    assert create_llm_from_config(config).use_responses_api is True
