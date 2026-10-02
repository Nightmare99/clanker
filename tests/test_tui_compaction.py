"""Compaction must yield to the TUI, cancel safely, and reuse retained history."""

import asyncio
from types import SimpleNamespace
from typing import Annotated
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from clanker.config.settings import Settings
from clanker.memory.checkpointer import SessionManager
from clanker.ui.app import ClankerApp
from clanker.ui.console import Console


class State(TypedDict):
    messages: Annotated[list, add_messages]


def checkpoint_graph(manager):
    workflow = StateGraph(State)
    workflow.add_node("model", lambda state: {})
    workflow.add_edge(START, "model")
    workflow.add_edge("model", END)
    return workflow.compile(checkpointer=manager.checkpointer)


class SummaryModel:
    profile = {"max_input_tokens": 100_000}
    _llm_type = "fake-chat"

    def __init__(self, *, wait=False):
        self.started = asyncio.Event()
        self.wait = wait
        self.cancelled = False
        self.requests = []

    def with_retry(self, **kwargs):
        return self

    def invoke(self, *args, **kwargs):
        raise AssertionError("TUI compaction must not call the blocking model API")

    async def ainvoke(self, *args, **kwargs):
        self.requests.append(args[0])
        self.started.set()
        if self.wait:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return SimpleNamespace(text="## SUMMARY\nPreserved session intent and next steps.")


def make_app(tmp_path, monkeypatch):
    monkeypatch.setattr(ClankerApp, "_load_history", lambda self: [])
    monkeypatch.setattr(ClankerApp, "_save_history", lambda self: None)
    app = ClankerApp(Console())
    app._play_hero = AsyncMock()
    app._settings = Settings()
    app._settings.context.keep_recent_turns = 1
    manager = SessionManager(workspace_path=str(tmp_path), model_name="session-model")
    manager.save_conversation_snapshot = MagicMock()
    app._session_manager = manager
    app._conversation_messages = [HumanMessage(content="Imported request"), AIMessage(content="Reply")]
    app._pending_restore_messages = list(app._conversation_messages)
    return app


@pytest.mark.asyncio
async def test_compaction_remains_responsive_and_ctrl_c_cancels(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    original = list(app._conversation_messages)
    model = SummaryModel(wait=True)
    create_model = MagicMock(return_value=model)
    monkeypatch.setattr("clanker.agent.create_model", create_model)
    graph_factory = MagicMock()
    monkeypatch.setattr("clanker.agent.graph.create_agent_graph", graph_factory)

    async with app.run_test(size=(100, 30)) as pilot:
        assert app._handle_slash_command("/compact") == "skip"
        await asyncio.wait_for(model.started.wait(), timeout=2)
        assert app._compacting
        # UI events still execute while the model call is pending.
        prompt = app.get_prompt_input()
        prompt.value = "Keep this draft"
        app._submit_prompt()
        assert prompt.value == "Keep this draft"
        app._handle_slash_command("/clear")
        assert app._conversation_messages == original
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert model.cancelled
        assert not app._processing
        assert not app._compacting
        assert app._conversation_messages == original
        assert app._pending_restore_messages == original
        app._session_manager.save_conversation_snapshot.assert_not_called()
        graph_factory.assert_not_called()
        create_model.assert_called_once_with(app._settings, model_name="session-model")


@pytest.mark.asyncio
async def test_success_updates_checkpoint_and_clears_import_replay(tmp_path, monkeypatch):
    from langchain.agents import create_agent
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

    from clanker.agent.summarization import RobustSummarizationMiddleware

    app = make_app(tmp_path, monkeypatch)
    original_list = app._conversation_messages
    model = SummaryModel()
    monkeypatch.setattr("clanker.agent.create_model", lambda *args, **kwargs: model)
    graph_model = FakeMessagesListChatModel(responses=[AIMessage(content="Latest answer")])
    graph_model.profile = {"max_input_tokens": 100_000}
    graph = create_agent(
        model=graph_model, tools=[], checkpointer=app._session_manager.checkpointer,
        middleware=[RobustSummarizationMiddleware(
            model=graph_model, trigger=("messages", 100), keep=("messages", 2),
        )],
    )
    await graph.ainvoke(
        {"messages": [HumanMessage(content="Current checkpoint context")]},
        app._session_manager.get_config(),
    )
    monkeypatch.setattr("clanker.agent.graph.create_agent_graph", lambda *args, **kwargs: graph)

    async with app.run_test(size=(100, 30)) as pilot:
        app._handle_slash_command("/compact")
        await asyncio.wait_for(app.workers.wait_for_complete(), timeout=3)
        await pilot.pause()
        assert app._conversation_messages is original_list
        assert "Preserved session intent" in original_list[0].content
        assert app._pending_restore_messages == []
        assert not app._processing
        assert "Current checkpoint context" in model.requests[0]
        assert "Imported request" not in model.requests[0]
        app._session_manager.save_conversation_snapshot.assert_called_once_with(original_list)
        next_turn = await graph.ainvoke(
            {"messages": [HumanMessage(content="Continue after compaction")]},
            app._session_manager.get_config(),
        )
        contents = [message.content for message in next_turn["messages"]]
        assert "Imported request" not in contents
        assert "Current checkpoint context" not in contents
        assert contents[-1] == "Continue after compaction"


@pytest.mark.asyncio
async def test_checkpoint_failure_keeps_history_and_resets_processing(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    original = list(app._conversation_messages)
    monkeypatch.setattr("clanker.agent.create_model", lambda *args, **kwargs: SummaryModel())
    graph = MagicMock()
    graph.aupdate_state = AsyncMock(side_effect=RuntimeError("Checkpoint unavailable"))
    monkeypatch.setattr("clanker.agent.graph.create_agent_graph", lambda *args, **kwargs: graph)
    async with app.run_test(size=(100, 30)):
        app._handle_slash_command("/compact")
        await asyncio.wait_for(app.workers.wait_for_complete(), timeout=3)
        assert app._conversation_messages == original
        assert app._pending_restore_messages == original
        assert not app._processing
        app._session_manager.save_conversation_snapshot.assert_not_called()


def test_imported_history_sync_uses_real_checkpoint_without_second_model_call(tmp_path, monkeypatch):
    from clanker.cli import sync_conversation_after_auto_compaction

    manager = SessionManager(workspace_path=str(tmp_path), model_name="session-model")
    manager.save_conversation_snapshot = MagicMock()
    graph = checkpoint_graph(manager)
    summary = HumanMessage(content="Existing imported-conversation summary")
    tool_call = AIMessage(content="", tool_calls=[{
        "name": "read_file", "args": {}, "id": "call1",
    }])
    final = AIMessage(content=[{"type": "reasoning", "encrypted_content": "private"},
                               {"type": "text", "text": "Latest answer"}])
    graph.update_state(manager.get_config(), {"messages": [
        summary, tool_call, ToolMessage(content="file contents", tool_call_id="call1"), final,
    ]})
    imported = [HumanMessage(content=f"Imported message {index}") for index in range(4424)]
    original_list = imported
    monkeypatch.setattr("clanker.cli.create_model", MagicMock(side_effect=AssertionError("No extra model call")))

    sync_conversation_after_auto_compaction(imported, manager, Settings(), MagicMock())

    assert imported is original_list
    assert [message.content for message in imported] == [summary.content, "Latest answer"]
    assert not imported[1].tool_calls
    assert manager.get_checkpoint_messages()[0].content == summary.content
    manager.save_conversation_snapshot.assert_called_once_with(imported)
