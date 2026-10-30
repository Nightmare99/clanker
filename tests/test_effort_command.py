"""Runtime effort command uses the active model and existing capability rules."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from clanker.cli import CommandCompleter, handle_command
from clanker.config.models import ModelConfig
from clanker.ui.app import _SLASH_COMMANDS, ClankerApp
from clanker.ui.chat_log import MessageType
from clanker.ui.console import _HELP_SECTIONS


@pytest.fixture
def active_model():
    return ModelConfig(name="active", provider="OpenAI", model="gpt-5.2", reasoning_effort="medium")


@pytest.mark.parametrize(("command", "effort"), [("/effort HIGH", "high"), ("/effort default", None), ("/effort none", "none")])
def test_changes_active_model_only(active_model, command, effort):
    console, chat = MagicMock(), MagicMock()
    manager = SimpleNamespace(model_name="active")
    with patch("clanker.cli.get_model_by_name", return_value=active_model), patch(
        "clanker.cli.get_default_model"
    ) as default, patch("clanker.config.models.add_model") as save:
        handle_command(command, console, manager, chat_log=chat)
    assert save.call_args.args[0].reasoning_effort == effort
    assert save.call_args.args[0].name == "active"
    assert active_model.reasoning_effort == "medium"
    default.assert_not_called()
    chat.add_message.assert_called_once()
    assert chat.add_message.call_args.args[1] == MessageType.SUCCESS


@pytest.mark.parametrize("command", ["/effort", "/effort minimal", "/effort high extra"])
def test_show_and_invalid_do_not_save(active_model, command):
    console = MagicMock()
    with patch("clanker.cli.get_model_by_name", return_value=active_model), patch(
        "clanker.config.models.add_model"
    ) as save:
        handle_command(command, console, SimpleNamespace(model_name="active"))
    save.assert_not_called()
    if command == "/effort":
        assert "Supported levels" in console.print_info.call_args.args[0]
    else:
        console.print_warning.assert_called_once()


def test_no_model():
    console = MagicMock()
    with patch("clanker.cli.get_default_model", return_value=None):
        handle_command("/effort high", console, SimpleNamespace(model_name=None))
    assert "No model configured" in console.print_warning.call_args.args[0]


def test_tui_busy_guard():
    app = MagicMock()
    app._processing = True
    assert ClankerApp._handle_slash_command(app, "/effort high") == "skip"
    assert app.get_chat_log.return_value.add_message.call_args.args[1] == MessageType.WARNING


def test_completions_and_registration(active_model):
    assert "/effort" in _SLASH_COMMANDS
    assert "/effort" in CommandCompleter.COMMANDS
    assert any(cmd.startswith("/effort") for _, rows in _HELP_SECTIONS for cmd, _ in rows)
    app = SimpleNamespace(_session_manager=SimpleNamespace(model_name="active"))
    with patch("clanker.config.get_model_by_name", return_value=active_model):
        assert ClankerApp._complete_subcommand(app, "/effort", "hi") == ["high", "xhigh"]


def test_unsupported_provider_can_reset():
    model = ModelConfig(name="local", provider="Ollama", model="qwen3")
    with patch("clanker.cli.get_default_model", return_value=model), patch(
        "clanker.config.models.add_model"
    ) as save:
        handle_command("/effort default", MagicMock(), SimpleNamespace(model_name=None))
    assert save.call_args.args[0].reasoning_effort is None


def test_saved_effort_used_by_next_model_construction(tmp_path, monkeypatch, active_model):
    from clanker.agent.graph import create_model
    from clanker.config import models

    monkeypatch.setattr(models, "MODELS_CONFIG_PATH", tmp_path / "models.json")
    models.add_model(active_model)
    handle_command("/effort high", MagicMock(), SimpleNamespace(model_name="active"))
    with patch("clanker.agent.graph.create_llm_from_config") as factory:
        create_model(model_name="active")
    assert factory.call_args.args[0].reasoning_effort == "high"
    handle_command("/effort default", MagicMock(), SimpleNamespace(model_name="active"))
    assert models.get_model_by_name("active").reasoning_effort is None
