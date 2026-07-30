"""Tests for injecting queued user messages into the agent's context mid-run.

Injection works by cleanly stopping the current `astream_events` generator and
resuming the same thread with the queued messages as the new input (the
checkpointer + add_messages reducer append them). We do NOT call
`graph.aupdate_state` while a generator for that thread is still active --
concurrent writes race with the graph's own checkpoint writes.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage


def _make_stateful_astream_events(call_events: list[list[dict]]):
    """Return an astream_events stub yielding a different event list per call."""
    calls: list[dict] = []

    def astream_events(state, config, version):
        calls.append({"state": state, "config": config, "version": version})
        index = len(calls) - 1
        events = call_events[index] if index < len(call_events) else []

        async def gen():
            for e in events:
                yield e

        return gen()

    return astream_events, calls


@pytest.mark.asyncio
async def test_pending_messages_restart_stream_with_new_input() -> None:
    """Queued messages cause a clean restart of astream_events with them as input."""
    queue: asyncio.Queue[str] = asyncio.Queue()
    queue.put_nowait("first follow-up")
    queue.put_nowait("second follow-up")

    astream_events, calls = _make_stateful_astream_events(
        [
            [{"event": "on_chat_model_start", "run_id": "r1"}],
            [],  # second call (after restart) completes with no more events
        ]
    )

    mock_graph = MagicMock()
    mock_graph.astream_events = astream_events
    mock_graph.aupdate_state = AsyncMock()

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
        await stream_agent_response_async(
            settings=MagicMock(),
            checkpointer=None,
            state={"messages": []},
            config={"configurable": {"thread_id": "test"}},
            console=MagicMock(),
            input_queue=queue,
        )

    # No concurrent aupdate_state calls against the live checkpoint.
    mock_graph.aupdate_state.assert_not_called()

    # astream_events was called twice: once for the original run, once to
    # resume the same thread with the queued messages as input.
    assert len(calls) == 2
    injected = calls[1]["state"]["messages"]
    assert len(injected) == 2
    assert all(isinstance(m, HumanMessage) for m in injected)
    assert [m.content for m in injected] == ["first follow-up", "second follow-up"]
    # Same thread/config across the restart.
    assert calls[1]["config"] == calls[0]["config"]

    # Queue is drained.
    assert queue.empty()


@pytest.mark.asyncio
async def test_no_restart_when_queue_empty() -> None:
    """astream_events is called exactly once when there are no pending messages."""
    queue: asyncio.Queue[str] = asyncio.Queue()

    astream_events, calls = _make_stateful_astream_events(
        [[{"event": "on_chat_model_start", "run_id": "r1"}]]
    )

    mock_graph = MagicMock()
    mock_graph.astream_events = astream_events
    mock_graph.aupdate_state = AsyncMock()

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
        await stream_agent_response_async(
            settings=MagicMock(),
            checkpointer=None,
            state={"messages": []},
            config={"configurable": {"thread_id": "test"}},
            console=MagicMock(),
            input_queue=queue,
        )

    assert len(calls) == 1
    mock_graph.aupdate_state.assert_not_called()


@pytest.mark.asyncio
async def test_no_restart_when_queue_is_none() -> None:
    """No injection attempted (and no crash) when input_queue is None (e.g. CLI mode)."""
    astream_events, calls = _make_stateful_astream_events(
        [[{"event": "on_chat_model_start", "run_id": "r1"}]]
    )

    mock_graph = MagicMock()
    mock_graph.astream_events = astream_events
    mock_graph.aupdate_state = AsyncMock()

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
        await stream_agent_response_async(
            settings=MagicMock(),
            checkpointer=None,
            state={"messages": []},
            config={"configurable": {"thread_id": "test"}},
            console=MagicMock(),
        )

    assert len(calls) == 1
    mock_graph.aupdate_state.assert_not_called()
