"""Keyboard shortcut reference for the main workspace."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static


class ShortcutHelpScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("f1", "close", "Close"),
    ]

    DEFAULT_CSS = """
    ShortcutHelpScreen { align: center middle; }
    ShortcutHelpScreen > VerticalScroll {
        width: 64;
        max-width: 90%;
        height: auto;
        max-height: 85%;
        border: round rgb(0,240,240);
        background: black;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(
                "[bold cyan]Keyboard shortcuts[/]\n\n"
                "[cyan]F1[/]          Shortcut help\n"
                "[cyan]F2[/]          Subagent tasks\n"
                "[cyan]F3[/]          Conversation history\n"
                "[cyan]F4[/]          File changes\n"
                "[cyan]Ctrl+Up / F5[/] Multiline Markdown message\n"
                "[cyan]Ctrl+C[/]      Copy selection / interrupt agent\n"
                "[cyan]Ctrl+D[/]      Quit\n"
                "[cyan]Up / Down[/]   Input history / completion choices\n"
                "              Composer history at top / bottom\n"
                "[cyan]Tab[/]         Complete commands\n"
                "[cyan]Enter[/]       Send message / queue follow-up\n"
                "[cyan]Esc[/]         Close popup or completions / clear input\n\n"
                "[dim]/help lists commands.\nEsc or F1 to close.[/]"
            )

    def action_close(self) -> None:
        self.dismiss()
