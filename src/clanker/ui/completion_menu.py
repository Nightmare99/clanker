"""Completion menu for slash commands — activated only via explicit Tab."""

from __future__ import annotations

from collections.abc import Callable
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.geometry import Offset
from textual.widgets import Static

# Commands that accept subcommand arguments for completion
_SUBCOMMAND_CMDS = {"/model", "/skill", "/workflow", "/restore"}

# Cap on visible rows before the menu scrolls instead of growing further.
# Kept in sync with the CSS max-height below (+2 there accounts for the border).
_MAX_VISIBLE_ITEMS = 10


class CompletionMenu(VerticalScroll):
    """Drop-up menu showing matching slash commands above the input bar.

    A leaf ``Static`` clamped by ``max-height`` + ``overflow-y`` reports its
    *displayed* (already-clamped) size as its own virtual size in Textual, so
    it never actually becomes scrollable -- there's nothing declaring the true,
    unclamped content extent. A ``VerticalScroll`` is a real scroll container:
    its virtual size tracks its child's natural (unclamped) height, so once
    that child is taller than the max-height, scrolling genuinely works.
    """

    DEFAULT_CSS = f"""
    CompletionMenu {{
        width: auto;
        height: auto;
        max-height: {_MAX_VISIBLE_ITEMS + 2};
        background: rgb(15, 15, 15);
        border: round rgb(0, 240, 240);
        padding: 0 1;
        color: rgb(200, 200, 200);
        display: none;
        layer: overlay;
    }}

    CompletionMenu.visible {{
        display: block;
    }}

    CompletionMenu > Static {{
        width: auto;
        height: auto;
    }}
    """

    def __init__(self, commands: list[str]) -> None:
        super().__init__(id="completion-menu")
        self._content = Static("")
        self._all_commands = commands
        self._matches: list[str] = []
        self._highlight_index = 0
        # Named distinctly from Widget's own internal `_render_cache` (a
        # `_RenderCache` object set during Textual's render cycle) -- reusing
        # that name causes render() to intermittently return the wrong type.
        self._menu_text: Text = Text()
        # Signature: (cmd: str, arg_prefix: str) -> list[str]
        self._subcommand_completer: Callable[[str, str], list[str]] | None = None
        # Whether the user has taken keyboard control of the menu (via Tab).
        # Shown as a hint until then.
        self._engaged = False

    def compose(self) -> ComposeResult:
        yield self._content

    # -- public API ------------------------------------------------------------

    def set_subcommand_completer(self, completer: Callable[[str, str], list[str]]) -> None:
        """Set a dynamic completer for subcommand arguments."""
        self._subcommand_completer = completer

    def compute_matches(self, text: str) -> list[str]:
        """Pure computation: return candidates for *text*. No side effects."""
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower() if parts else ""
        arg_prefix = parts[1] if len(parts) > 1 else ""

        if self._subcommand_completer and cmd in _SUBCOMMAND_CMDS:
            matches = self._subcommand_completer(cmd, arg_prefix)
            return [f"{cmd} {m}" for m in matches]

        return [c for c in self._all_commands if c.startswith(text)]

    def show(self, text: str, engaged: bool = False) -> None:
        """Populate, position, and display the menu for *text*."""
        self._matches = self.compute_matches(text)
        self._highlight_index = 0
        self._engaged = engaged

        if not self._matches:
            self.hide()
            return

        self._build_render()
        self._position()
        self.add_class("visible")
        self.scroll_to(y=0, animate=False)

    def set_engaged(self, engaged: bool) -> None:
        """Toggle the "Tab to select" hint without recomputing matches."""
        if engaged != self._engaged:
            self._engaged = engaged
            self._build_render()
            self.refresh()

    def hide(self) -> None:
        """Remove the menu from view."""
        self._engaged = False
        self.remove_class("visible")

    def next_item(self, wrap: bool = True) -> None:
        if not self._matches:
            return
        if wrap:
            self._highlight_index = (self._highlight_index + 1) % len(self._matches)
        elif self._highlight_index < len(self._matches) - 1:
            self._highlight_index += 1
        self._build_render()
        self._scroll_to_highlight()
        self.refresh()

    def prev_item(self, wrap: bool = True) -> None:
        if not self._matches:
            return
        if wrap:
            self._highlight_index = (self._highlight_index - 1) % len(self._matches)
        elif self._highlight_index > 0:
            self._highlight_index -= 1
        self._build_render()
        self._scroll_to_highlight()
        self.refresh()

    def get_selected(self) -> str | None:
        if self._matches:
            return self._matches[self._highlight_index]
        return None

    # -- internals -------------------------------------------------------------

    def _build_render(self) -> None:
        """Build the Rich Text and push it into the inner content widget."""
        self._menu_text = Text()
        for i, item in enumerate(self._matches):
            if i == self._highlight_index:
                self._menu_text.append(f"> {item}\n", style="bold rgb(0,240,240)")
            else:
                self._menu_text.append(f"  {item}\n")
        if not self._engaged:
            self._menu_text.append("Tab to select", style="dim italic rgb(120,120,120)")
        self._content.update(self._menu_text)

    def _scroll_to_highlight(self) -> None:
        """Scroll the menu so the highlighted row is within the visible window."""
        line = self._highlight_index
        top = self.scroll_offset.y
        if line < top:
            self.scroll_to(y=line, animate=False)
        elif line >= top + _MAX_VISIBLE_ITEMS:
            self.scroll_to(y=line - _MAX_VISIBLE_ITEMS + 1, animate=False)

    def _position(self) -> None:
        """Position immediately above the input bar, left-aligned."""
        if not self.is_attached:
            return
        screen = self.screen
        hint_lines = 0 if self._engaged else 1
        content_lines = min(len(self._matches) + hint_lines, _MAX_VISIBLE_ITEMS)
        menu_height = content_lines + 2  # +2 for border
        y = screen.size.height - 1 - 1 - menu_height
        if y < 1:
            y = 1
        self.offset = Offset(2, y)
