"""Tests that thinking/response text from EVERY model call in a turn reaches
the chat log -- not just the final call's.

Regression test for a bug where ``current_response``/``current_thinking``
were reset on each new ``on_chat_model_start`` event without first being
flushed, silently dropping any reasoning/text produced by intermediate model
calls (e.g. the "let me check that file" thinking step right before a tool
call) in a multi-step tool-calling turn.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _chunk(content):
    return SimpleNamespace(content=content)


def _make_astream_events(events):
    async def astream_events(state, config, version):
        for e in events:
            yield e

    def bound(state, config, version):
        return astream_events(state, config, version)

    return bound


@pytest.mark.asyncio
async def test_intermediate_call_thinking_reaches_chat_log() -> None:
    """Thinking from a model call that leads into a tool call must not be dropped.

    Sequence: call 1 thinks, then calls a tool. Call 2 (after the tool
    result) gives the final plain-text answer. Both the intermediate
    thinking and the final response should be added to the chat log.
    """
    events = [
        {"event": "on_chat_model_start", "run_id": "r1"},
        {
            "event": "on_chat_model_stream",
            "data": {"chunk": _chunk([{"type": "thinking", "thinking": "Let me check that file first."}])},
        },
        {
            "event": "on_tool_start",
            "run_id": "t1",
            "name": "read_file",
            "data": {"input": {"file_path": "foo.py"}},
        },
        {
            "event": "on_tool_end",
            "run_id": "t1",
            "name": "read_file",
            "data": {"output": "ok"},
        },
        # Second model call -- its on_chat_model_start reset must first
        # flush call 1's accumulated thinking, not silently drop it.
        {"event": "on_chat_model_start", "run_id": "r2"},
        {
            "event": "on_chat_model_stream",
            "data": {"chunk": _chunk([{"type": "text", "text": "The file looks fine."}])},
        },
    ]

    mock_graph = MagicMock()
    mock_graph.astream_events = _make_astream_events(events)

    chat_log = MagicMock()
    textual_app = MagicMock()
    textual_app.get_chat_log.return_value = chat_log

    console = MagicMock()
    console._textual_app = textual_app

    settings = MagicMock()
    settings.output.show_tool_calls = True

    from clanker.ui.streaming import stream_agent_response_async

    with patch(
        "clanker.agent.create_agent_graph_async",
        new_callable=AsyncMock,
        return_value=(mock_graph, MagicMock()),
    ), patch(
        "clanker.ui.streaming._teardown_live_displays"
    ), patch(
        "clanker.ui.streaming._heal_orphaned_tool_calls",
        new_callable=AsyncMock,
    ):
        result = await stream_agent_response_async(
            settings=settings,
            checkpointer=None,
            state={"messages": []},
            config={"configurable": {"thread_id": "test"}},
            console=console,
        )

    from clanker.ui.chat_log import MessageType

    assistant_calls = [
        c for c in chat_log.add_message.call_args_list
        if len(c.args) > 1 and c.args[1] == MessageType.ASSISTANT
    ]

    # Thinking now renders via its own dedicated method (styled like a tool
    # call: badge header + card body) rather than the generic add_message.
    assert chat_log.add_thinking.called, "intermediate call's thinking never reached the chat log"
    assert "Let me check that file first." in chat_log.add_thinking.call_args_list[0].args[0]

    assert assistant_calls, "final response never reached the chat log"
    assert "The file looks fine." in assistant_calls[0].args[0]

    # The returned StreamResult still reports the final answer, not "".
    assert result.response == "The file looks fine."
