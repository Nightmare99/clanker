"""The active session stays visible and its exit hint points to saved history."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage
from rich.console import Console as RichConsole
from textual.widgets import Label

import clanker.cli as cli_mod
from clanker.memory.checkpointer import SessionManager
from clanker.ui.app import ClankerApp
from clanker.ui.console import Console


async def test_tui_session_id_updates_after_clear(tmp_path, monkeypatch):
    monkeypatch.setattr("clanker.tools.todo_tools.get_todo_store", MagicMock())
    console = Console()
    console._console = RichConsole(file=io.StringIO(), force_terminal=False, width=100)
    app = ClankerApp(console)
    app._play_hero = AsyncMock()
    app._session_manager = SessionManager(workspace_path=str(tmp_path))
    app._conversation_messages = [HumanMessage(content="Previous task")]
    app._pending_restore_messages = list(app._conversation_messages)
    previous_id = app._session_manager.session_id

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        label = app.query_one("#status-session", Label)
        assert previous_id in str(label.render())

        app._handle_slash_command("/clear")
        await pilot.pause()
        current_id = app._session_manager.session_id
        assert current_id != previous_id
        assert current_id in str(label.render())
        assert previous_id not in str(label.render())
        assert app._conversation_messages == []
        assert app._pending_restore_messages == []
        assert [m.content for m in app._session_manager.get_session_messages(previous_id)] == ["Previous task"]

        app._restore_session(previous_id)
        await pilot.pause()
        assert previous_id in str(label.render())
        assert [m.content for m in app._conversation_messages] == ["Previous task"]


def test_tui_exit_prints_saved_session_id_and_resume_command(monkeypatch):
    output = io.StringIO()
    console = Console()
    console._console = RichConsole(file=output, force_terminal=False, width=100)
    manager = MagicMock()
    manager.session_id = "abc12345"
    app = MagicMock()

    def finish_session():
        app._conversation_messages.append(HumanMessage(content="Completed task"))

    app.run.side_effect = finish_session
    monkeypatch.setattr(cli_mod, "SessionManager", MagicMock(return_value=manager))
    monkeypatch.setattr(cli_mod, "get_default_model", MagicMock(return_value=None))
    monkeypatch.setattr(cli_mod, "create_model", MagicMock())
    monkeypatch.setattr(cli_mod, "cleanup_event_loop", MagicMock())
    with patch("clanker.agent.prompts.load_user_instructions", return_value=""), \
         patch("clanker.ui.app.ClankerApp", return_value=app), \
         patch("clanker.update.get_update_info", return_value=None):
        cli_mod.run_interactive(console, settings=MagicMock())

    manager.save_conversation_snapshot.assert_called_once_with(app._conversation_messages)
    assert "Session ID: abc12345" in output.getvalue()
    assert "clanker --resume abc12345" in output.getvalue()


def test_legacy_exit_prints_resumed_session_id(tmp_path, monkeypatch):
    output = io.StringIO()
    console = Console()
    console._console = RichConsole(file=output, force_terminal=False, width=100)
    console.print_welcome = MagicMock()
    manager = MagicMock()
    manager.session_id = "saved123"
    manager.model_name = None
    manager.get_session_messages.return_value = [HumanMessage(content="Earlier task")]
    settings = MagicMock()
    settings.memory.storage_path = tmp_path
    prompt_session = MagicMock()
    prompt_session.prompt.return_value = "/exit"

    monkeypatch.setattr(cli_mod, "SessionManager", MagicMock(return_value=manager))
    monkeypatch.setattr(cli_mod, "get_default_model", MagicMock(return_value=None))
    monkeypatch.setattr(cli_mod, "create_model", MagicMock())
    monkeypatch.setattr(cli_mod, "cleanup_event_loop", MagicMock())
    with patch("clanker.agent.prompts.load_user_instructions", return_value=""), \
         patch("prompt_toolkit.PromptSession", return_value=prompt_session):
        cli_mod.run_interactive_legacy(console, settings, resume_session="saved123")

    manager.save_conversation_snapshot.assert_called_once()
    assert "Session ID: saved123" in output.getvalue()
    assert "clanker --resume saved123" in output.getvalue()
