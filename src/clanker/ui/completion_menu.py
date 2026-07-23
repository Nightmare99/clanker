"""Drop-up completion menu for slash commands."""

from __future__ import annotations

from collections.abc import Callable
from rich.text import Text
from textual.widgets import Static


# Commands that accept subcommand arguments for completion
_SUBCOMMAND_CMDS = {"/model", "/skill", "/workflow", "/restore"}


class CompletionMenu(Static):
    """Drop-up menu showing matching slash commands above the input bar."""

    DEFAULT_CSS = """
    CompletionMenu {
        width: auto;
        height: auto;
        background: rgb(15, 15, 15);
        border: round rgb(0, 240, 240);
        padding: 0 1;
        color: rgb(200, 200, 200);
        display: none;
        layer: overlay;
    }

    CompletionMenu.visible {
        display: block;
    }
    """

    def __init__(self, commands: list[str]) -> None:
        super().__init__("", id="completion-menu")
        self._all_commands = commands
        self._matches: list[str] = []
        self._highlight_index = 0
        self._current_prefix = ""
        self._render_text: Text = Text("")
        # Signature: (cmd: str, arg_prefix: str) -> list[str]
        self._subcommand_completer: Callable[[str, str], list[str]] | None = None

    def set_subcommand_completer(self, completer: Callable[[str, str], list[str]]) -> None:
        """Set a dynamic completer for subcommand arguments."""
        self._subcommand_completer = completer

    def show(self, text: str) -> None:
        """Show matching completions for the given input text."""
        self._current_prefix = text
        self._highlight_index = 0

        parts = text.split(maxsplit=1)
        cmd = parts[0].lower() if parts else ""
        arg_prefix = parts[1] if len(parts) > 1 else ""

        # Subcommand argument completion (e.g., /model <tab>)
        if self._subcommand_completer and cmd in _SUBCOMMAND_CMDS:
            self._matches = self._subcommand_completer(cmd, arg_prefix)
            self._matches = [f"{cmd} {m}" for m in self._matches]
        else:
            # Top-level command completion
            self._matches = [c for c in self._all_commands if c.startswith(text)]

        if not self._matches:
            self._set_visible(False)
            return

        if self._highlight_index >= len(self._matches):
            self._highlight_index = 0

        self._build_render()
        self._set_visible(True)
        self.refresh()
        # Position above the input bar after layout resolves
        self.call_after_refresh(self._position_above_input)

    def _position_above_input(self) -> None:
        """Position the menu above the input bar, aligned left."""
        if not self.is_attached or not self.visible:
            return
        from textual.geometry import Offset
        screen = self.screen
        # Menu height = matches + 2 for border
        menu_height = len(self._matches) + 2
        # Position: y = screen_height - prompt_bar(1) - gap(1) - menu_height
        y = screen.size.height - 1 - 1 - menu_height
        self.offset = Offset(2, y)

    def hide(self) -> None:
        self._set_visible(False)

    def next_item(self) -> None:
        if not self._matches:
            return
        self._highlight_index = (self._highlight_index + 1) % len(self._matches)
        self._build_render()
        self.refresh()

    def prev_item(self) -> None:
        if not self._matches:
            return
        self._highlight_index = (self._highlight_index - 1) % len(self._matches)
        self._build_render()
        self.refresh()

    def _build_render(self) -> None:
        """Build the Rich Text for rendering without calling update()."""
        self._render_text = Text()
        for i, item in enumerate(self._matches):
            if i == self._highlight_index:
                self._render_text.append(f"> {item}\n", style="bold rgb(0,240,240)")
            else:
                self._render_text.append(f"  {item}\n")

    def render(self) -> Text:
        return self._render_text

    def get_selected(self) -> str | None:
        if self._matches:
            return self._matches[self._highlight_index]
        return None

    def _set_visible(self, visible: bool) -> None:
        if visible:
            self.add_class("visible")
        else:
            self.remove_class("visible")
