"""Unit tests for the spawn_subagent tool and streaming context isolation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from clanker.tools.subagent import spawn_subagent
from clanker.ui.streaming import (
    StreamResult,
    get_active_console,
    stream_agent_response_async,
    _local_state,
)
from clanker.tools.notify_tools import get_notify_callback, set_notify_callback
from clanker.tools.ask_tools import get_ask_callback, set_ask_callback
from clanker.tools.bash_tools import get_approval_callback, set_approval_callback


@pytest.mark.asyncio
async def test_spawn_subagent_success() -> None:
    """spawn_subagent successfully runs stream_agent_response_async and returns a dictionary."""
    mock_result = StreamResult(
        response="Subagent output task complete",
        input_tokens=15,
        output_tokens=10,
    )

    with patch(
        "clanker.ui.streaming.stream_agent_response_async",
        new_callable=AsyncMock,
        return_value=mock_result,
    ) as mock_stream:
        res = await spawn_subagent.ainvoke(
            {"prompt": "Run a test", "system_prompt": "You are a test helper"}
        )

        assert res["success"] is True
        assert res["response"] == "Subagent output task complete"
        assert res["input_tokens"] == 15
        assert res["output_tokens"] == 10

        # Verify stream_agent_response_async is called with proper args
        mock_stream.assert_called_once()
        kwargs = mock_stream.call_args[1]
        assert kwargs["checkpointer"] is None
        assert kwargs["system_prompt"] == "You are a test helper"
        assert len(kwargs["state"]["messages"]) == 1
        assert isinstance(kwargs["state"]["messages"][0], HumanMessage)
        assert kwargs["state"]["messages"][0].content == "Run a test"


@pytest.mark.asyncio
async def test_spawn_subagent_failure() -> None:
    """spawn_subagent handles exceptions raised inside stream_agent_response_async and returns error dictionary."""
    with patch(
        "clanker.ui.streaming.stream_agent_response_async",
        new_callable=AsyncMock,
        side_effect=ValueError("LLM API quota exceeded"),
    ):
        res = await spawn_subagent.ainvoke({"prompt": "Run another test"})

        assert res["success"] is False
        assert "error" in res
        assert "LLM API quota exceeded" in res["error"]


@pytest.mark.asyncio
async def test_callback_preservation() -> None:
    """stream_agent_response_async isolates/restores parent console and callbacks in nesting environments."""
    parent_console = MagicMock()
    child_console = MagicMock()

    parent_notify = MagicMock()
    parent_ask = MagicMock()
    parent_approval = MagicMock()

    # Pre-register parent callbacks
    set_notify_callback(parent_notify)
    set_ask_callback(parent_ask)
    set_approval_callback(parent_approval)
    _local_state.active_console = parent_console

    mock_result = StreamResult(response="Done")

    # We mock the inner graph execution to check that callbacks are set during execution
    # but restored when the execution exits.
    async def fake_stream(*args, **kwargs) -> StreamResult:
        # Inside execution, callbacks should match what is passed, but wait!
        # stream_agent_response_async registers new local callbacks
        assert get_notify_callback() is not parent_notify
        assert get_ask_callback() is not parent_ask
        assert get_approval_callback() is not parent_approval
        assert get_active_console() is child_console
        return mock_result

    # Let's mock create_agent_graph_async to avoid actual LangGraph construction
    # and just mock the graph execution loop to test the outer try/finally wrapper
    with patch(
        "clanker.agent.create_agent_graph_async",
        new_callable=AsyncMock,
        return_value=(MagicMock(), MagicMock()),
    ), patch(
        "clanker.ui.streaming._teardown_live_displays"
    ), patch(
        "clanker.ui.streaming._heal_orphaned_tool_calls",
        new_callable=AsyncMock,
    ):
        # We need to run stream_agent_response_async to see if it sets and restores
        # active console and callbacks.
        # Let's mock the event stream loop or let it exit early.
        # Actually, let's patch the async generator astream_events to return an empty generator.
        async def empty_generator(*args, **kwargs):
            # Assert inside execution context
            assert get_notify_callback() is not parent_notify
            assert get_ask_callback() is not parent_ask
            assert get_approval_callback() is not parent_approval
            assert get_active_console() is child_console
            for x in []:
                yield x

        with patch(
            "langgraph.prebuilt.chat_agent_executor.create_react_agent",  # or mock graph
            return_value=MagicMock(),
        ) as mock_create:
            mock_graph = MagicMock()
            mock_graph.astream_events = empty_generator

            with patch(
                "clanker.agent.create_agent_graph_async",
                new_callable=AsyncMock,
                return_value=(mock_graph, MagicMock()),
            ):
                await stream_agent_response_async(
                    settings=MagicMock(),
                    checkpointer=None,
                    state={"messages": []},
                    config={"configurable": {"thread_id": "test"}},
                    console=child_console,
                )

    # After execution exits, parent callbacks and console must be restored
    assert get_notify_callback() is parent_notify
    assert get_ask_callback() is parent_ask
    assert get_approval_callback() is parent_approval
    assert get_active_console() is parent_console

    # Cleanup
    set_notify_callback(None)
    set_ask_callback(None)
    set_approval_callback(None)
    _local_state.active_console = None
