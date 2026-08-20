"""Tests for run_interactive's control flow after wrapping startup in a
loading spinner (see cli.py).

The setup steps between `clanker` being typed and the TUI appearing --
session manager init, model validation, the GitHub update check -- got moved
inside a `with console.loading_spinner(...)` block so the user sees feedback
instead of a silent gap. These tests guard the restructuring itself: that
`app.run()` still only happens after setup succeeds and the spinner has
closed, that a model-validation failure still exits cleanly (the spinner
must not swallow or delay the exit), and that post-`run()` cleanup still
fires.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console as RichConsole

import clanker.cli as cli_mod
from clanker.ui.console import Console


@pytest.fixture
def console() -> Console:
    c = Console()
    c._console = RichConsole(file=io.StringIO(), force_terminal=False, width=80)
    return c


def _fake_model() -> MagicMock:
    model = MagicMock()
    model.name = "claude-opus"
    model.provider = "Anthropic"
    model.max_input_tokens = 200_000
    return model


class TestRunInteractiveHappyPath:
    def test_app_run_called_once_after_setup_completes(self, console: Console, monkeypatch) -> None:
        fake_model = _fake_model()
        fake_session_manager = MagicMock()
        fake_app = MagicMock()

        monkeypatch.setattr(cli_mod, "SessionManager", MagicMock(return_value=fake_session_manager))
        monkeypatch.setattr(cli_mod, "get_default_model", MagicMock(return_value=fake_model))
        monkeypatch.setattr(cli_mod, "create_model", MagicMock())
        monkeypatch.setattr(cli_mod, "cleanup_event_loop", MagicMock())

        with patch("clanker.agent.prompts.load_user_instructions", return_value=""), \
             patch("clanker.ui.app.ClankerApp", return_value=fake_app), \
             patch("clanker.update.get_update_info", return_value=None):
            cli_mod.run_interactive(console, settings=MagicMock())

        fake_app.run.assert_called_once()

    def test_app_state_is_wired_before_run(self, console: Console, monkeypatch) -> None:
        fake_model = _fake_model()
        fake_session_manager = MagicMock()
        fake_app = MagicMock()
        settings = MagicMock()

        monkeypatch.setattr(cli_mod, "SessionManager", MagicMock(return_value=fake_session_manager))
        monkeypatch.setattr(cli_mod, "get_default_model", MagicMock(return_value=fake_model))
        monkeypatch.setattr(cli_mod, "create_model", MagicMock())
        monkeypatch.setattr(cli_mod, "cleanup_event_loop", MagicMock())

        with patch("clanker.agent.prompts.load_user_instructions", return_value=""), \
             patch("clanker.ui.app.ClankerApp", return_value=fake_app), \
             patch("clanker.update.get_update_info", return_value=None):
            cli_mod.run_interactive(console, settings=settings)

        assert fake_app._session_manager is fake_session_manager
        assert fake_app._settings is settings
        assert console._textual_app is fake_app

    def test_cleanup_runs_after_app_exits(self, console: Console, monkeypatch) -> None:
        fake_model = _fake_model()
        fake_session_manager = MagicMock()
        fake_app = MagicMock()
        cleanup_mock = MagicMock()

        monkeypatch.setattr(cli_mod, "SessionManager", MagicMock(return_value=fake_session_manager))
        monkeypatch.setattr(cli_mod, "get_default_model", MagicMock(return_value=fake_model))
        monkeypatch.setattr(cli_mod, "create_model", MagicMock())
        monkeypatch.setattr(cli_mod, "cleanup_event_loop", cleanup_mock)

        with patch("clanker.agent.prompts.load_user_instructions", return_value=""), \
             patch("clanker.ui.app.ClankerApp", return_value=fake_app), \
             patch("clanker.update.get_update_info", return_value=None):
            cli_mod.run_interactive(console, settings=MagicMock())

        cleanup_mock.assert_called_once()

    def test_update_check_failure_does_not_block_startup(self, console: Console, monkeypatch) -> None:
        """get_update_info() is a network call wrapped in try/except in
        cli.py -- if it raises (offline, DNS failure, etc.) startup must
        still complete and reach app.run()."""
        fake_model = _fake_model()
        fake_session_manager = MagicMock()
        fake_app = MagicMock()

        monkeypatch.setattr(cli_mod, "SessionManager", MagicMock(return_value=fake_session_manager))
        monkeypatch.setattr(cli_mod, "get_default_model", MagicMock(return_value=fake_model))
        monkeypatch.setattr(cli_mod, "create_model", MagicMock())
        monkeypatch.setattr(cli_mod, "cleanup_event_loop", MagicMock())

        with patch("clanker.agent.prompts.load_user_instructions", return_value=""), \
             patch("clanker.ui.app.ClankerApp", return_value=fake_app), \
             patch("clanker.update.get_update_info", side_effect=RuntimeError("offline")):
            cli_mod.run_interactive(console, settings=MagicMock())

        fake_app.run.assert_called_once()


class TestRunInteractiveModelValidationFailure:
    def test_invalid_model_config_exits_without_starting_app(self, console: Console, monkeypatch) -> None:
        fake_session_manager = MagicMock()
        fake_app_cls = MagicMock()

        monkeypatch.setattr(cli_mod, "SessionManager", MagicMock(return_value=fake_session_manager))
        monkeypatch.setattr(cli_mod, "get_default_model", MagicMock(return_value=None))
        monkeypatch.setattr(cli_mod, "create_model", MagicMock(side_effect=ValueError("no model configured")))

        with patch("clanker.ui.app.ClankerApp", fake_app_cls), pytest.raises(SystemExit) as exc_info:
            cli_mod.run_interactive(console, settings=MagicMock())

        assert exc_info.value.code == 1
        fake_app_cls.assert_not_called()

    def test_spinner_is_cleared_even_on_exit(self, console: Console, monkeypatch) -> None:
        """sys.exit() inside the `with console.loading_spinner(...)` block
        raises SystemExit through it -- the spinner's __exit__ must still
        run and leave no stray output behind."""
        monkeypatch.setattr(cli_mod, "SessionManager", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(cli_mod, "get_default_model", MagicMock(return_value=None))
        monkeypatch.setattr(cli_mod, "create_model", MagicMock(side_effect=ValueError("no model configured")))

        with pytest.raises(SystemExit):
            cli_mod.run_interactive(console, settings=MagicMock())

        output = console._console.file.getvalue()
        assert "Booting up" not in output
