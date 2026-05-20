"""Tests for fancy Markdown UI rendering and Console updates."""

from unittest.mock import MagicMock, patch
from rich.console import Console as RichConsole
from rich.panel import Panel
from clanker.ui.console import Console
from clanker.config import get_settings


def test_print_assistant_message_basic() -> None:
    """Verify that print_assistant_message renders a Panel and does not raise errors."""
    console = Console()
    
    # Mock self._console.print to verify it is called with a Panel
    console._console.print = MagicMock()
    
    test_message = "This is a **bold** markdown response."
    console.print_assistant_message(test_message)
    
    assert console._console.print.called
    args, kwargs = console._console.print.call_args
    panel = args[0]
    
    assert isinstance(panel, Panel)
    # Check that panel has title including configured agent name
    settings = get_settings()
    agent_name = settings.agent.name or "Clanker"
    assert agent_name in str(panel.title)


def test_print_assistant_message_empty() -> None:
    """Verify that print_assistant_message handles empty/whitespace inputs gracefully."""
    console = Console()
    console._console.print = MagicMock()
    
    console.print_assistant_message("")
    console.print_assistant_message("   \n   ")
    
    assert not console._console.print.called


def test_print_assistant_message_custom_agent_name() -> None:
    """Verify that print_assistant_message uses custom agent name when set in settings."""
    console = Console()
    console._console.print = MagicMock()
    
    # Mock settings.agent.name
    with patch.object(console._settings.agent, "name", "AlphaBot"):
        console.print_assistant_message("Hello from the other side.")
        
        assert console._console.print.called
        args, kwargs = console._console.print.call_args
        panel = args[0]
        
        assert isinstance(panel, Panel)
        assert "AlphaBot" in str(panel.title)
