"""Tests for fancy Markdown UI rendering and Console updates."""

from unittest.mock import MagicMock

from rich.markdown import Markdown
from rich.panel import Panel

from clanker.ui.console import Console


def test_print_assistant_message_basic() -> None:
    """print_assistant_message renders a green-bordered Markdown panel."""
    console = Console()

    # Mock self._console.print to verify it is called with a Panel
    console._console.print = MagicMock()

    test_message = "This is a **bold** markdown response."
    console.print_assistant_message(test_message)

    assert console._console.print.called
    args, kwargs = console._console.print.call_args
    panel = args[0]

    assert isinstance(panel, Panel)
    # The assistant panel uses a green left-border style (no title in the
    # current design — the panel is borderless apart from the green edge).
    assert panel.border_style == "green"
    # The message is rendered as Markdown inside the panel.
    assert isinstance(panel.renderable, Markdown)
    assert panel.renderable.markup == test_message


def test_print_assistant_message_empty() -> None:
    """Verify that print_assistant_message handles empty/whitespace inputs gracefully."""
    console = Console()
    console._console.print = MagicMock()

    console.print_assistant_message("")
    console.print_assistant_message("   \n   ")

    assert not console._console.print.called


def test_print_assistant_message_preserves_content() -> None:
    """The full message content is preserved in the rendered panel."""
    console = Console()
    console._console.print = MagicMock()

    console.print_assistant_message("Hello from the other side.")

    assert console._console.print.called
    args, kwargs = console._console.print.call_args
    panel = args[0]

    assert isinstance(panel, Panel)
    assert isinstance(panel.renderable, Markdown)
    assert "Hello from the other side." in panel.renderable.markup

