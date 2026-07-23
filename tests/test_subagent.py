"""Unit tests for the spawn_subagent tool and streaming context isolation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from clanker.tools.ask_tools import get_ask_callback, set_ask_callback
from clanker.tools.bash_tools import get_approval_callback, set_approval_callback
from clanker.tools.notify_tools import get_notify_callback, set_notify_callback
from clanker.tools.subagent import spawn_subagent
from clanker.ui.streaming import (
    StreamResult,
    _local_state,
    get_active_console,
    stream_agent_response_async,
)


@pytest.mark.asyncio
async def test_spawn_subagent_success() -> None:
    """spawn_subagent runs stream_agent_response_async in a dedicated thread and returns a dictionary."""
    mock_result = StreamResult(
        response="Subagent output task complete",
        input_tokens=15,
        output_tokens=10,
    )

    mock_agent = MagicMock()
    mock_agent.name = "test-agent"
    mock_agent.system_prompt = "You are a test helper agent"
    mock_agent.tools = []

    with patch(
        "clanker.tools.subagent.load_agent_config",
        return_value=mock_agent,
    ), patch(
        "clanker.ui.streaming.stream_agent_response_async",
        new_callable=AsyncMock,
        return_value=mock_result,
    ) as mock_stream, patch(
        "clanker.ui.streaming.get_active_console",
    ):
        res = await spawn_subagent.ainvoke(
            {"agent_name": "test-agent", "prompt": "Run a test"}
        )

        assert res["success"] is True
        assert res["agent"] == "test-agent"
        assert "summary" in res
        assert "Subagent output task complete" in res["summary"]
        assert res["input_tokens"] == 15
        assert res["output_tokens"] == 10

        mock_stream.assert_called_once()
        kwargs = mock_stream.call_args[1]
        assert kwargs["checkpointer"] is None
        assert kwargs["system_prompt"] == "You are a test helper agent"
        assert len(kwargs["state"]["messages"]) == 1
        assert isinstance(kwargs["state"]["messages"][0], HumanMessage)
        assert kwargs["state"]["messages"][0].content == "Run a test"


@pytest.mark.asyncio
async def test_spawn_subagent_agent_not_found() -> None:
    """spawn_subagent returns error when agent config is not found."""
    with patch(
        "clanker.tools.subagent.load_agent_config",
        return_value=None,
    ), patch(
        "clanker.agents.list_agents",
        return_value={"code-reviewer": MagicMock(), "tester": MagicMock()},
    ):
        res = await spawn_subagent.ainvoke(
            {"agent_name": "nonexistent", "prompt": "Run a test"}
        )

        assert res["success"] is False
        assert "error" in res
        assert "nonexistent" in res["error"]


@pytest.mark.asyncio
async def test_spawn_subagent_failure() -> None:
    """spawn_subagent handles exceptions raised inside stream_agent_response_async."""
    mock_agent = MagicMock()
    mock_agent.name = "test-agent"
    mock_agent.system_prompt = "You are a test helper agent"
    mock_agent.tools = []

    with patch(
        "clanker.tools.subagent.load_agent_config",
        return_value=mock_agent,
    ), patch(
        "clanker.ui.streaming.stream_agent_response_async",
        new_callable=AsyncMock,
        side_effect=ValueError("LLM API quota exceeded"),
    ), patch(
        "clanker.ui.streaming.get_active_console",
    ):
        res = await spawn_subagent.ainvoke(
            {"agent_name": "test-agent", "prompt": "Run another test"}
        )

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

    set_notify_callback(parent_notify)
    set_ask_callback(parent_ask)
    set_approval_callback(parent_approval)
    _local_state.active_console = parent_console

    StreamResult(response="Done")

    async def empty_generator(*args, **kwargs):
        assert get_notify_callback() is not parent_notify
        assert get_ask_callback() is not parent_ask
        assert get_approval_callback() is not parent_approval
        assert get_active_console() is child_console
        for x in []:
            yield x

    mock_graph = MagicMock()
    mock_graph.astream_events = empty_generator

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
            console=child_console,
        )

    assert get_notify_callback() is parent_notify
    assert get_ask_callback() is parent_ask
    assert get_approval_callback() is parent_approval
    assert get_active_console() is parent_console

    set_notify_callback(None)
    set_ask_callback(None)
    set_approval_callback(None)
    _local_state.active_console = None
