"""Tests for continuous loop execution mode."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from clanker.cli import handle_command
from clanker.runtime import (
    get_last_loop_goal,
    get_loop_goal,
    is_loop_mode,
    set_loop_mode,
)
from clanker.ui.console import Console


@pytest.fixture(autouse=True)
def reset_loop_state():
    """Ensure loop mode state is clean before and after each test."""
    set_loop_mode(False)
    # Clear both flags
    import clanker.runtime as rt
    rt._loop_mode = False
    rt._loop_goal = ""
    rt._last_loop_goal = ""
    yield
    set_loop_mode(False)
    rt._loop_mode = False
    rt._loop_goal = ""
    rt._last_loop_goal = ""


class TestRuntimeLoopState:
    """Tests for runtime loop state management."""

    def test_set_and_clear_loop_mode(self):
        assert not is_loop_mode()
        assert get_loop_goal() == ""
        assert get_last_loop_goal() == ""

        set_loop_mode(True, "Fix all failing tests")
        assert is_loop_mode()
        assert get_loop_goal() == "Fix all failing tests"
        assert get_last_loop_goal() == "Fix all failing tests"

        set_loop_mode(False)
        assert not is_loop_mode()
        assert get_loop_goal() == ""
        assert get_last_loop_goal() == "Fix all failing tests"

    def test_resume_previous_goal_when_toggled_without_arg(self):
        set_loop_mode(True, "Build user profile page")
        set_loop_mode(False)
        assert not is_loop_mode()
        assert get_last_loop_goal() == "Build user profile page"

        # Re-enabling without explicit goal should resume previous goal
        set_loop_mode(True)
        assert is_loop_mode()
        assert get_loop_goal() == "Build user profile page"

    def test_updating_goal(self):
        set_loop_mode(True, "Goal 1")
        assert get_loop_goal() == "Goal 1"

        set_loop_mode(True, "Goal 2")
        assert get_loop_goal() == "Goal 2"
        assert get_last_loop_goal() == "Goal 2"


class TestHandleLoopCommand:
    """Tests for /loop command parsing and execution."""

    def test_loop_with_explicit_goal(self):
        console = MagicMock(spec=Console)
        manager = SimpleNamespace(model_name="test-model")

        res = handle_command("/loop Run unit tests and fix errors", console, manager, [])
        assert res == "loop:start:Run unit tests and fix errors"
        assert is_loop_mode()
        assert get_loop_goal() == "Run unit tests and fix errors"

    def test_loop_off_and_stop_commands(self):
        console = MagicMock(spec=Console)
        manager = SimpleNamespace(model_name="test-model")

        set_loop_mode(True, "My goal")
        assert is_loop_mode()

        res = handle_command("/loop off", console, manager, [])
        assert res == "loop:off"
        assert not is_loop_mode()

        set_loop_mode(True, "My goal")
        res = handle_command("/loop stop", console, manager, [])
        assert res == "loop:off"
        assert not is_loop_mode()

    def test_loop_toggle_off_when_active(self):
        console = MagicMock(spec=Console)
        manager = SimpleNamespace(model_name="test-model")

        set_loop_mode(True, "Active task")
        res = handle_command("/loop", console, manager, [])
        assert res == "loop:off"
        assert not is_loop_mode()

    def test_loop_toggle_on_with_previous_goal(self):
        console = MagicMock(spec=Console)
        manager = SimpleNamespace(model_name="test-model")

        set_loop_mode(True, "Previous goal")
        set_loop_mode(False)

        res = handle_command("/loop", console, manager, [])
        assert res == "loop:start:Previous goal"
        assert is_loop_mode()
        assert get_loop_goal() == "Previous goal"

    def test_loop_toggle_on_from_conversation_history(self):
        console = MagicMock(spec=Console)
        manager = SimpleNamespace(model_name="test-model")

        messages = [
            HumanMessage(content="Refactor the database queries"),
            AIMessage(content="Refactored 3 queries so far."),
        ]

        res = handle_command("/loop", console, manager, messages)
        assert res == "loop:start:Refactor the database queries"
        assert is_loop_mode()
        assert get_loop_goal() == "Refactor the database queries"

    def test_loop_toggle_without_goal_or_history_prints_usage(self):
        console = MagicMock(spec=Console)
        manager = SimpleNamespace(model_name="test-model")

        res = handle_command("/loop", console, manager, [])
        assert res is None
        assert not is_loop_mode()
        console.print_info.assert_called()

    def test_loop_on_command(self):
        console = MagicMock(spec=Console)
        manager = SimpleNamespace(model_name="test-model")

        messages = [HumanMessage(content="Make tests green")]
        res = handle_command("/loop on", console, manager, messages)
        assert res == "loop:start:Make tests green"
        assert is_loop_mode()

        # If already on, /loop on reports already active
        res2 = handle_command("/loop on", console, manager, messages)
        assert res2 is None
        assert is_loop_mode()


class TestTuiLoopModeIntegration:
    """Tests for TUI integration of loop mode."""

    def test_workspace_status_loop_label(self):
        from clanker.ui.status_bar import WorkspaceStatus

        status = WorkspaceStatus()
        # Verify set_loop_mode method exists and does not crash
        status.set_loop_mode(True, "Test goal")
        status.set_loop_mode(False)

    def test_app_complete_subcommand_loop(self):
        from clanker.ui.app import ClankerApp

        console = Console()
        app = ClankerApp(console=console)
        set_loop_mode(False)
        comps = app._complete_subcommand("/loop", "")
        assert "on" in comps
        assert "off" in comps

        set_loop_mode(True, "Working")
        comps_active = app._complete_subcommand("/loop", "")
        assert "off" in comps_active
        assert "stop" in comps_active

    def test_action_interrupt_stops_loop_mode(self):
        from clanker.ui.app import ClankerApp

        console = Console()
        app = ClankerApp(console=console)
        set_loop_mode(True, "Continuous task")
        assert is_loop_mode()

        timer_mock = MagicMock()
        app._loop_timer = timer_mock

        app.action_interrupt()
        assert not is_loop_mode()
        assert app.interrupt_requested is True
        timer_mock.stop.assert_called_once()
        assert app._loop_timer is None
