"""Tests for /reload command and session reloading."""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console as RichConsole

import clanker.cli as cli_mod
from clanker.memory.checkpointer import SessionManager
from clanker.ui.app import _SLASH_COMMANDS, ClankerApp
from clanker.ui.chat_log import MessageType
from clanker.ui.console import _HELP_SECTIONS, Console


@pytest.fixture
def console() -> Console:
    c = Console()
    c._console = RichConsole(file=io.StringIO(), force_terminal=False, width=80)
    return c


@pytest.fixture
def session_manager(tmp_path: Path) -> SessionManager:
    return SessionManager(workspace_path=str(tmp_path))


class TestBuildReloadArgs:
    """Tests for constructing reload command-line arguments."""

    def test_empty_args_adds_resume(self) -> None:
        args = cli_mod.build_reload_args([], "sess-123", yolo=False)
        assert args == ["--resume", "sess-123"]

    def test_adheres_to_yolo_true(self) -> None:
        args = cli_mod.build_reload_args([], "sess-123", yolo=True)
        assert args == ["--resume", "sess-123", "--yolo"]

    def test_adheres_to_yolo_false_removes_old_yolo(self) -> None:
        args = cli_mod.build_reload_args(["--yolo", "--no-tui"], "sess-123", yolo=False)
        assert "--yolo" not in args
        assert args == ["--no-tui", "--resume", "sess-123"]

    def test_replaces_old_resume_flag(self) -> None:
        args = cli_mod.build_reload_args(["--resume", "old-sess", "--no-tui"], "new-sess", yolo=False)
        assert "old-sess" not in args
        assert args == ["--no-tui", "--resume", "new-sess"]

    def test_replaces_old_short_r_flag(self) -> None:
        args = cli_mod.build_reload_args(["-r", "old-sess"], "new-sess", yolo=False)
        assert "old-sess" not in args
        assert args == ["--resume", "new-sess"]

    def test_replaces_old_resume_equals_flag(self) -> None:
        args = cli_mod.build_reload_args(["--resume=old-sess", "--yolo"], "new-sess", yolo=True)
        assert "--resume=old-sess" not in args
        assert args == ["--resume", "new-sess", "--yolo"]

    def test_replaces_old_r_equals_flag(self) -> None:
        args = cli_mod.build_reload_args(["-r=old-sess"], "new-sess", yolo=False)
        assert "-r=old-sess" not in args
        assert args == ["--resume", "new-sess"]

    def test_updates_model_flag_when_originally_specified(self) -> None:
        args = cli_mod.build_reload_args(
            ["-m", "gpt-4o", "--no-tui"],
            "sess-123",
            yolo=False,
            active_model="claude-3-5-sonnet",
        )
        assert args == ["--no-tui", "--resume", "sess-123", "--model", "claude-3-5-sonnet"]

    def test_updates_model_equals_flag_when_originally_specified(self) -> None:
        args = cli_mod.build_reload_args(
            ["--model=gpt-4o"],
            "sess-123",
            yolo=False,
            active_model="claude-3-5-sonnet",
        )
        assert args == ["--resume", "sess-123", "--model", "claude-3-5-sonnet"]

    def test_preserves_original_model_on_cli_override(self) -> None:
        args = cli_mod.build_reload_args(
            ["--provider", "Anthropic", "--model", "custom-temp"],
            "sess-123",
            yolo=False,
            active_model="cli-override",
        )
        assert args == ["--provider", "Anthropic", "--resume", "sess-123", "--model", "custom-temp"]

    def test_does_not_inject_model_flag_if_not_originally_specified(self) -> None:
        args = cli_mod.build_reload_args(
            ["--no-tui"],
            "sess-123",
            yolo=False,
            active_model="claude-3-5-sonnet",
        )
        assert "--model" not in args
        assert args == ["--no-tui", "--resume", "sess-123"]


class TestHandleCommandReload:
    """Tests for /reload command handling."""

    def test_handle_command_returns_reload(self, console: Console, session_manager: SessionManager) -> None:
        chat_log = MagicMock()
        res = cli_mod.handle_command("/reload", console, session_manager, [], chat_log=chat_log)
        assert res == "reload"
        chat_log.add_message.assert_called_once_with("Reloading session...", MessageType.SYSTEM)

    def test_handle_command_handles_whitespace(self, console: Console, session_manager: SessionManager) -> None:
        res = cli_mod.handle_command("  /reload  ", console, session_manager, [])
        assert res == "reload"


class TestAppSlashCommandReload:
    """Tests for TUI /reload handling."""

    def test_reload_blocked_when_processing(self, console: Console) -> None:
        app = ClankerApp(console)
        app._processing = True
        chat_log = MagicMock()
        app.get_chat_log = MagicMock(return_value=chat_log)

        res = app._handle_slash_command("/reload")
        assert res == "skip"
        chat_log.add_message.assert_called_once()
        assert "Wait for the current operation" in chat_log.add_message.call_args[0][0]

    def test_reload_saves_snapshot_and_returns_reload(self, console: Console, session_manager: SessionManager) -> None:
        app = ClankerApp(console)
        app._processing = False
        app._session_manager = session_manager
        app._conversation_messages = []
        chat_log = MagicMock()
        app.get_chat_log = MagicMock(return_value=chat_log)

        with patch.object(session_manager, "save_conversation_snapshot") as mock_save:
            res = app._handle_slash_command("/reload")
            assert res == "reload"
            mock_save.assert_called_once_with([], force=True)

    def test_submit_exits_with_reload_result(self, console: Console, session_manager: SessionManager) -> None:
        app = ClankerApp(console)
        app._processing = False
        app._session_manager = session_manager
        app._conversation_messages = []
        app.get_chat_log = MagicMock()
        app.exit = MagicMock()

        prompt_input = MagicMock()
        prompt_input.value = "/reload"
        prompt_input.pop_expanded_value.return_value = ("/reload", [])
        app.get_prompt_input = MagicMock(return_value=prompt_input)

        app._submit_prompt()
        app.exit.assert_called_once_with(result="reload")


class TestReloadClankerExecution:
    """Tests for the reload_clanker execution helper."""

    def test_reload_frozen_binary(self, session_manager: SessionManager, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", "/usr/local/bin/clanker")
        monkeypatch.setattr(sys, "argv", ["/usr/local/bin/clanker", "--yolo"])
        monkeypatch.setattr(cli_mod, "is_yolo_mode", lambda: True)

        execv_mock = MagicMock()
        monkeypatch.setattr(os, "execv", execv_mock)

        cli_mod.reload_clanker(session_manager)
        execv_mock.assert_called_once()
        target, argv = execv_mock.call_args[0]
        assert target == "/usr/local/bin/clanker"
        assert argv == ["/usr/local/bin/clanker", "--resume", session_manager.session_id, "--yolo"]

    def test_reload_script_non_frozen(self, session_manager: SessionManager, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        monkeypatch.setattr(sys, "executable", "/venv/bin/python")
        monkeypatch.setattr(sys, "argv", ["clanker", "--no-tui"])
        monkeypatch.setattr(cli_mod, "is_yolo_mode", lambda: False)
        monkeypatch.setattr(shutil, "which", lambda s: "/venv/bin/clanker")
        monkeypatch.setattr(os.path, "isfile", lambda p: True)
        monkeypatch.setattr(os, "access", lambda p, mode: True)

        execv_mock = MagicMock()
        monkeypatch.setattr(os, "execv", execv_mock)

        cli_mod.reload_clanker(session_manager)
        execv_mock.assert_called_once()
        target, argv = execv_mock.call_args[0]
        assert target == "/venv/bin/clanker"
        assert argv == ["/venv/bin/clanker", "--no-tui", "--resume", session_manager.session_id]


class TestRunInteractiveReloadFlow:
    """Tests that run_interactive triggers reload when app exits with result='reload'."""

    def test_run_interactive_triggers_reload(self, console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_session_manager = MagicMock()
        fake_session_manager.session_id = "sess-test"
        fake_session_manager.model_name = "test-model"
        fake_app = MagicMock()
        fake_app.run.return_value = "reload"
        fake_app._conversation_messages = []

        cleanup_mock = MagicMock()
        reload_mock = MagicMock()
        hint_mock = MagicMock()

        monkeypatch.setattr(cli_mod, "SessionManager", MagicMock(return_value=fake_session_manager))
        monkeypatch.setattr(cli_mod, "get_default_model", MagicMock(return_value=None))
        monkeypatch.setattr(cli_mod, "create_model", MagicMock())
        monkeypatch.setattr(cli_mod, "cleanup_event_loop", cleanup_mock)
        monkeypatch.setattr(cli_mod, "reload_clanker", reload_mock)
        monkeypatch.setattr(cli_mod, "_print_resume_hint", hint_mock)

        with patch("clanker.agent.prompts.load_user_instructions", return_value=""), \
             patch("clanker.ui.app.ClankerApp", return_value=fake_app), \
             patch("clanker.update.get_update_info", return_value=None):
            cli_mod.run_interactive(console, settings=MagicMock())

        fake_session_manager.save_conversation_snapshot.assert_called_once_with([], force=True)
        cleanup_mock.assert_called_once()
        reload_mock.assert_called_once_with(fake_session_manager)
        hint_mock.assert_not_called()


class TestLegacyInteractiveReloadFlow:
    """Tests that run_interactive_legacy triggers reload on /reload."""

    def test_legacy_triggers_reload(self, tmp_path: Path, console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_session_manager = MagicMock()
        fake_session_manager.session_id = "sess-legacy"
        fake_session_manager.model_name = None
        prompt_session = MagicMock()
        prompt_session.prompt.return_value = "/reload"

        settings = MagicMock()
        settings.memory.storage_path = tmp_path

        cleanup_mock = MagicMock()
        reload_mock = MagicMock()
        hint_mock = MagicMock()

        monkeypatch.setattr(cli_mod, "SessionManager", MagicMock(return_value=fake_session_manager))
        monkeypatch.setattr(cli_mod, "get_default_model", MagicMock(return_value=None))
        monkeypatch.setattr(cli_mod, "create_model", MagicMock())
        monkeypatch.setattr(cli_mod, "cleanup_event_loop", cleanup_mock)
        monkeypatch.setattr(cli_mod, "reload_clanker", reload_mock)
        monkeypatch.setattr(cli_mod, "_print_resume_hint", hint_mock)

        with patch("clanker.agent.prompts.load_user_instructions", return_value=""), \
             patch("prompt_toolkit.PromptSession", return_value=prompt_session):
            cli_mod.run_interactive_legacy(console, settings)

        fake_session_manager.save_conversation_snapshot.assert_called_once_with([], force=True)
        cleanup_mock.assert_called_once()
        reload_mock.assert_called_once_with(fake_session_manager)
        hint_mock.assert_not_called()


class TestEmptySessionSnapshotAndResume:
    """Tests that saving an empty session snapshot with force=True allows resuming."""

    def test_empty_snapshot_saves_and_resumes(self, tmp_path: Path) -> None:
        sm1 = SessionManager(workspace_path=str(tmp_path))
        s_id = sm1.session_id
        sm1.save_conversation_snapshot([], force=True)

        # File should exist on disk
        conv_file = sm1._storage.conversations_dir / f"{s_id}.json"
        assert conv_file.exists()
        with open(conv_file, encoding="utf-8") as f:
            data = json.load(f)
        assert data["messages"] == []
        assert data["message_count"] == 0

        # sm2 resumes it
        sm2 = SessionManager(workspace_path=str(tmp_path))
        messages = sm2.get_session_messages(s_id)
        assert messages is not None
        assert messages == []


class TestCompleterAndHelpDiscovery:
    """Tests discovery of /reload in completers and help."""

    def test_slash_commands_list_includes_reload(self) -> None:
        assert "/reload" in _SLASH_COMMANDS

    def test_command_completer_includes_reload(self) -> None:
        assert "/reload" in cli_mod.CommandCompleter.COMMANDS

    def test_help_sections_includes_reload(self) -> None:
        system_commands = dict(_HELP_SECTIONS[0][1])
        assert "/reload" in system_commands
