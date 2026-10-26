"""Keyboard shortcut reference for the main workspace."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from clanker.config.theme import get_theme_config, rgb_str
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
        pal = get_theme_config().palette
        acc = rgb_str(pal.secondary)
        pri = rgb_str(pal.primary)
        editing = (
            f"[bold {pri}]macOS editing shortcuts[/]\n"
            f"[{acc}]Cmd+C[/]       Copy selection (never interrupts)\n"
            f"[{acc}]Cmd+X / V[/]   Cut / paste in focused input\n"
            f"[{acc}]Cmd+A[/]       Select all in focused input\n"
            f"[{acc}]Cmd+Z[/]       Undo in composer\n"
            f"[{acc}]Cmd+Shift+Z[/] Redo in composer\n"
            "[dim]Copy needs no terminal key mapping.\n"
            "Other Command keys require terminal support.\n"
            "Ctrl+C always interrupts; Ctrl+D quits.\n\n[/]"
            if macos else
            f"[{acc}]Ctrl+X / V[/]  Cut / paste in focused input\n"
            f"[{acc}]Ctrl+Shift+A[/] Select all in prompt\n"
            f"[{acc}]F7[/]          Select all in composer\n"
            f"[{acc}]Ctrl+Z / Y[/]  Undo / redo in composer\n\n"
        )
        copy_or_interrupt = "Interrupt agent" if macos else "Copy selection / interrupt agent"
        with VerticalScroll():
            yield Static(
                f"[bold {pri}]Keyboard shortcuts[/]\n\n"
                f"[{acc}]Select text[/] Copies automatically on release\n"
                f"[{acc}]F1[/]          Shortcut help\n"
                f"[{acc}]F2[/]          Subagent tasks\n"
                f"[{acc}]F3[/]          Conversation history\n"
                f"[{acc}]F4[/]          File changes\n"
                f"[{acc}]Ctrl+Up / F5[/] Multiline Markdown message\n"
                f"[{acc}]F6[/]          Memories\n"
                f"[{acc}]Ctrl+C[/]      {copy_or_interrupt}\n"
                f"[{acc}]Ctrl+D[/]      Quit\n"
                f"[{acc}]{keyboard.edit_label('Enter')}[/]  Send from composer\n"
                f"[{acc}]Up / Down[/]   Input history / completion choices\n"
                "              Composer history at top / bottom\n"
                f"[{acc}]Tab[/]         Complete commands\n"
                f"[{acc}]Enter[/]       Send message / queue follow-up\n"
                f"[{acc}]Esc[/]         Close popup or completions / clear input\n\n"
                f"{editing}"
                "[dim]"
                "/help lists commands.\nEsc or F1 to close.[/]"
            )

    def action_close(self) -> None:
        self.dismiss()
