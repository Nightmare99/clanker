"""Real Copilot HTTP decoding, thinking display, and signed tool-call replay."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from clanker.config import copilot_auth
from clanker.config.models import ModelConfig
from clanker.config.settings import Settings
from tests.test_chatgpt import example_tool

REASONING = "Next I'll check the ECharts function strings."
SIGNATURE = "opaque-thinking-signature"


@pytest.mark.parametrize("mode", ["invoke", "ainvoke", "stream", "astream", "tui"])
async def test_copilot_claude_thinking_survives_tool_round_trip(monkeypatch, tmp_path, mode):
    from clanker.agent.graph import create_agent_graph
    from clanker.config import models
    from clanker.ui.streaming import stream_agent_response_async

    monkeypatch.setattr(models, "MODELS_CONFIG_PATH", tmp_path / "models.json")
    monkeypatch.setattr(copilot_auth, "get_valid_copilot_token", lambda: "test-token")
    requests = []

    def respond(request):
        assert request.url.path == "/chat/completions"
        payload = json.loads(request.content)
        requests.append(payload)
        first = len(requests) == 1
        message = {"role": "assistant", "content": "" if first else "Final answer"}
        if first:
            message.update(reasoning_text=REASONING, reasoning_opaque=SIGNATURE, tool_calls=[{
                "id": "tool-1", "type": "function",
                "function": {"name": "example_tool", "arguments": '{"query":"No matches"}'},
            }])
        base = {"id": "completion", "created": 1, "model": "claude-opus-5.5"}
        finish_reason = "tool_calls" if first else "stop"
        if not payload.get("stream"):
            return httpx.Response(200, json={**base, "object": "chat.completion", "choices": [{
                "index": 0, "message": message, "finish_reason": finish_reason,
            }]})
        deltas = [
            {"role": "assistant", "content": ""},
            {"reasoning_text": "Next I'll check "} if first else {"content": "Final "},
            {"reasoning_text": "the ECharts function strings.", "reasoning_opaque": SIGNATURE}
            if first else {"content": "answer"},
        ]
        if first:
            deltas.append({"tool_calls": [{"index": 0, **message["tool_calls"][0]}]})
        choices = [{"delta": delta, "finish_reason": None} for delta in deltas]
        choices.append({"delta": {}, "finish_reason": finish_reason})
        body = "".join(
            "data: " + json.dumps({**base, "object": "chat.completion.chunk", "choices": [{
                "index": 0, **choice,
            }]}) + "\n\n" for choice in choices
        ) + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    transport = httpx.MockTransport(respond)
    sync_client = httpx.Client(transport=transport)
    async_client = httpx.AsyncClient(transport=transport)
    monkeypatch.setattr(models, "_fresh_openai_http_clients", lambda: {
        "http_client": sync_client, "http_async_client": async_client,
    })
    config = ModelConfig(
        name="test-copilot-claude", provider="GitHubCopilot", model="claude-opus-5.5",
        max_input_tokens=200_000,
    )
    models.add_model(config)
    graph = create_agent_graph(
        Settings(), checkpointer=MemorySaver(), tools=[example_tool],
        model_name=config.name, system_prompt="Test",
    )
    state = {"messages": [HumanMessage(content="Look it up")]}
    graph_config = {"configurable": {"thread_id": mode}}
    try:
        if mode == "invoke":
            await asyncio.to_thread(graph.invoke, state, graph_config)
        elif mode == "ainvoke":
            await graph.ainvoke(state, graph_config)
        elif mode == "stream":
            await asyncio.to_thread(lambda: list(graph.stream(state, graph_config, stream_mode="messages")))
        elif mode == "astream":
            assert [event async for event in graph.astream_events(state, graph_config, version="v2")]
        else:
            console = MagicMock()
            monkeypatch.setattr("clanker.agent.create_agent_graph_async", AsyncMock(return_value=(graph, None)))
            result = await stream_agent_response_async(Settings(), None, state, graph_config, console)
            assert result.response == "Final answer"
            console.print_assistant_message.assert_called_once_with("Final answer")
            chat_log = console._textual_app.get_chat_log.return_value
            chat_log.add_thinking.assert_called_once_with(REASONING)
            calls = [call[0] for call in chat_log.method_calls]
            assert calls.index("add_thinking") < calls.index("add_tool_complete")
            assert SIGNATURE not in str(chat_log.mock_calls)

        assert len(requests) == 2
        replay = next(message for message in requests[1]["messages"] if message.get("tool_calls"))
        assert replay["content"] is None  # Thinking was never merged into assistant content.
        assert replay["reasoning_text"] == REASONING
        assert replay["reasoning_opaque"] == SIGNATURE
        snapshot = await graph.aget_state(graph_config)
        assert snapshot.values["messages"][-1].content == "Final answer"
    finally:
        sync_client.close()
        await async_client.aclose()
