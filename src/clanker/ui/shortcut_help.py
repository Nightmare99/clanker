"""Keyboard shortcut reference for the main workspace."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from clanker.ui import keyboard


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
        macos = keyboard.is_macos()
        editing = (
            "[bold cyan]macOS editing shortcuts[/]\n"
            "[cyan]Cmd+C[/]       Copy selection (never interrupts)\n"
            "[cyan]Cmd+X / V[/]   Cut / paste in focused input\n"
            "[cyan]Cmd+A[/]       Select all in focused input\n"
            "[cyan]Cmd+Z[/]       Undo in composer\n"
            "[cyan]Cmd+Shift+Z[/] Redo in composer\n"
            "[dim]Copy needs no terminal key mapping.\n"
            "Other Command keys require terminal support.\n"
            "Ctrl+C always interrupts; Ctrl+D quits.\n\n[/]"
            if macos else
            "[cyan]Ctrl+X / V[/]  Cut / paste in focused input\n"
            "[cyan]Ctrl+Shift+A[/] Select all in prompt\n"
            "[cyan]F7[/]          Select all in composer\n"
            "[cyan]Ctrl+Z / Y[/]  Undo / redo in composer\n\n"
        )
        copy_or_interrupt = "Interrupt agent" if macos else "Copy selection / interrupt agent"
        with VerticalScroll():
            yield Static(
                "[bold cyan]Keyboard shortcuts[/]\n\n"
                "[cyan]Select text[/] Copies automatically on release\n"
                "[cyan]F1[/]          Shortcut help\n"
                "[cyan]F2[/]          Subagent tasks\n"
                "[cyan]F3[/]          Conversation history\n"
                "[cyan]F4[/]          File changes\n"
                "[cyan]Ctrl+Up / F5[/] Multiline Markdown message\n"
                "[cyan]F6[/]          Memories\n"
                f"[cyan]Ctrl+C[/]      {copy_or_interrupt}\n"
                "[cyan]Ctrl+D[/]      Quit\n"
                f"[cyan]{keyboard.edit_label('Enter')}[/]  Send from composer\n"
                "[cyan]Up / Down[/]   Input history / completion choices\n"
                "              Composer history at top / bottom\n"
                "[cyan]Tab[/]         Complete commands\n"
                "[cyan]Enter[/]       Send message / queue follow-up\n"
                "[cyan]Esc[/]         Close popup or completions / clear input\n\n"
                f"{editing}"
                "[dim]"
                "/help lists commands.\nEsc or F1 to close.[/]"
            )

    def action_close(self) -> None:
        self.dismiss()
