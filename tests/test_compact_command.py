"""Tests for the /compact slash command."""

from __future__ import annotations

from typing import Annotated
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from clanker.cli import handle_command
from clanker.memory.checkpointer import SessionManager
from clanker.ui.console import Console


class State(TypedDict):
    messages: Annotated[list, add_messages]


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeModel:
    def __init__(self, text: str = "## SESSION INTENT\nTest intent\n\n## SUMMARY\nTest summary\n\n## ARTIFACTS\nNone\n\n## NEXT STEPS\nNone") -> None:
        self.text = text
        self._llm_type = "fake-chat"
        self.profile = {"max_input_tokens": 100_000}

    def invoke(self, *args, **kwargs):
        return FakeResponse(self.text)


@pytest.fixture
def console():
    c = Console()
    c.print_info = MagicMock()
    c.print_success = MagicMock()
    c.print_error = MagicMock()
    c.print_warning = MagicMock()
    return c


@pytest.fixture
def session_manager(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sm = SessionManager(workspace_path=str(tmp_path))
    # Mock save_conversation_snapshot to avoid disk/json serialization issues in basic tests
    sm.save_conversation_snapshot = MagicMock()
    return sm


def test_compact_empty_or_none(console, session_manager):
    # Test None messages
    res = handle_command("/compact", console, session_manager, conversation_messages=None)
    assert res is None
    console.print_warning.assert_called_with("No active conversation messages context to compact.")

    # Test empty messages
    res = handle_command("/compact", console, session_manager, conversation_messages=[])
    assert res is None
    console.print_info.assert_called_with("No conversation history to compact.")


def test_compact_too_short(console, session_manager, monkeypatch):
    # Mock settings.context.keep_recent_turns to 4 (requires 8 messages to keep)
    from clanker.config.settings import Settings
    settings = Settings()
    settings.context.keep_recent_turns = 4
    monkeypatch.setattr("clanker.config.get_settings", lambda: settings)

    # Mock model creation
    fake_model = FakeModel("## SESSION INTENT\nShort manual compaction test\n\n## SUMMARY\nCompacted 2 messages anyway\n\n## ARTIFACTS\nNone\n\n## NEXT STEPS\nNone")
    monkeypatch.setattr("clanker.cli.create_model", lambda *args, **kwargs: fake_model)

    # Mock graph.update_state to see if it receives the right updates
    from langgraph.graph import END, START, StateGraph

    workflow = StateGraph(State)
    workflow.add_node("node", lambda state: {"messages": []})
    workflow.add_edge(START, "node")
    workflow.add_edge("node", END)
    graph = workflow.compile(checkpointer=session_manager.checkpointer)

    monkeypatch.setattr("clanker.agent.graph.create_agent_graph", lambda *args, **kwargs: graph)

    messages = [HumanMessage(content="hello"), AIMessage(content="hi")]
    res = handle_command("/compact", console, session_manager, conversation_messages=messages)
    assert res is None
    console.print_success.assert_called()

    # With len=2, cutoff_index will be 1. So the 1st message is summarized, 2nd preserved.
    assert len(messages) == 2
    assert "Here is a summary of the conversation to date" in messages[0].content
    assert "hi" in messages[1].content


def test_compact_single_message(console, session_manager, monkeypatch):
    # Mock settings to keep only 2 messages (1 turn)
    from clanker.config.settings import Settings
    settings = Settings()
    settings.context.keep_recent_turns = 1
    monkeypatch.setattr("clanker.config.get_settings", lambda: settings)

    # Mock model creation
    fake_model = FakeModel("## SESSION INTENT\nSingle message manual compaction test\n\n## SUMMARY\nCompacted 1 message\n\n## ARTIFACTS\nNone\n\n## NEXT STEPS\nNone")
    monkeypatch.setattr("clanker.cli.create_model", lambda *args, **kwargs: fake_model)

    # Mock graph.update_state
    from langgraph.graph import END, START, StateGraph

    workflow = StateGraph(State)
    workflow.add_node("node", lambda state: {"messages": []})
    workflow.add_edge(START, "node")
    workflow.add_edge("node", END)
    graph = workflow.compile(checkpointer=session_manager.checkpointer)

    monkeypatch.setattr("clanker.agent.graph.create_agent_graph", lambda *args, **kwargs: graph)

    messages = [HumanMessage(content="just one message")]
    res = handle_command("/compact", console, session_manager, conversation_messages=messages)
    assert res is None
    console.print_success.assert_called()

    # With len=1, cutoff_index will be 1. So the only message is summarized.
    assert len(messages) == 1
    assert "Here is a summary of the conversation to date" in messages[0].content


def test_compact_success(console, session_manager, monkeypatch):
    # Mock settings to keep only 2 messages (1 turn)
    from clanker.config.settings import Settings
    settings = Settings()
    settings.context.keep_recent_turns = 1
    monkeypatch.setattr("clanker.config.get_settings", lambda: settings)

    # Mock model creation
    fake_model = FakeModel("## SESSION INTENT\nManual compaction test\n\n## SUMMARY\nCompacted 2 messages\n\n## ARTIFACTS\nNone\n\n## NEXT STEPS\nNone")
    monkeypatch.setattr("clanker.cli.create_model", lambda *args, **kwargs: fake_model)

    # Create 4 messages. With keep=2, cutoff will be 2. So the first 2 messages will be summarized.
    messages = [
        HumanMessage(content="msg 1"),
        AIMessage(content="msg 2"),
        HumanMessage(content="msg 3"),
        AIMessage(content="msg 4"),
    ]

    # Mock graph.update_state to see if it receives the right updates
    from langgraph.graph import END, START, StateGraph

    workflow = StateGraph(State)
    workflow.add_node("node", lambda state: {"messages": []})
    workflow.add_edge(START, "node")
    workflow.add_edge("node", END)
    graph = workflow.compile(checkpointer=session_manager.checkpointer)

    monkeypatch.setattr("clanker.agent.graph.create_agent_graph", lambda *args, **kwargs: graph)

    res = handle_command("/compact", console, session_manager, conversation_messages=messages)
    assert res is None
    console.print_success.assert_called()

    # The messages should be compacted: one summary message + preserved tail.
    assert len(messages) >= 1
    assert "Here is a summary of the conversation to date" in messages[0].content

    # The checkpointer state should also contain the compacted messages.
    config = session_manager.get_config()
    state = graph.get_state(config)
    state_messages = state.values.get("messages", [])
    assert len(state_messages) >= 1
    assert "Here is a summary of the conversation to date" in state_messages[0].content
