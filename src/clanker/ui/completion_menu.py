"""Completion menu for slash commands, subcommand arguments, and filesystem paths.

Provides a natural terminal-style autocomplete experience:
- Tab triggers or cycles completions.
- Single match or common prefix expands immediately into the input box.
- Multiple matches display a clean, themed dropdown menu above the prompt.
- Arrow keys / Tab / Shift+Tab navigate options; Enter / Tab accepts; Escape dismisses.
- Command descriptions and metadata are rendered alongside candidates.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.geometry import Offset
from textual.widgets import Static

# Cap on visible rows before the menu scrolls instead of growing further.
_MAX_VISIBLE_ITEMS = 8

# Mapping of built-in slash commands to friendly descriptions
_COMMAND_DESCRIPTIONS: dict[str, str] = {
    "/help": "Display help matrix & keyboard shortcuts",
    "/clear": "Wipe conversation history & start fresh",
    "/model": "Switch model or query active status",
    "/effort": "Change reasoning effort on the fly",
    "/compact": "Compact conversation history manually",
    "/reload": "Restart in-place preserving session & flags",
    "/history": "List past conversation sessions",
    "/restore": "Restore past conversation",
    "/resume": "Alias for /restore",
    "/import": "Import conversations from other CLI tools",
    "/memories": "Search and manage durable memories",
    "/remember": "Store durable information to memory",
    "/forget": "Delete a stored memory item",
    "/tasks": "View subagent execution history",
    "/changes": "Review & undo file modifications",
    "/workflow": "Run or list saved prompt workflows",
    "/skill": "Load a specialized skill capability",
    "/config": "Inspect active configuration parameters",
    "/mcp": "Show Model Context Protocol server status",
    "/logs": "Inspect diagnostic logs",
    "/copilot-login": "Authenticate GitHub Copilot subscription",
    "/antigravity-login": "Authenticate Google Antigravity account",
    "/openai-login": "Authenticate ChatGPT coding models account",
    "/exit": "Exit Clanker",
    "/quit": "Alias for /exit",
    "/q": "Alias for /exit",
}


@dataclass(frozen=True)
class CompletionItem:
    """A single completion candidate."""

    value: str  # The full completed text string to insert (or replace prefix with)
    display: str  # Short text shown in the menu list
    description: str = ""  # Optional right-aligned description or type label
    is_path: bool = False  # Whether this is a filesystem path
    is_dir: bool = False  # Whether this is a directory path


def complete_filepaths(prefix: str, root_dir: str | Path | None = None) -> list[CompletionItem]:
    """Find matching file and directory paths for autocomplete.

    Handles relative paths, home directories (~), and absolute paths.
    Appends a trailing slash for directories so consecutive Tab presses can continue navigating.
    """
    if not prefix:
        return []

    # Handle ~ expansion
    has_tilde = prefix.startswith("~")
    expanded_prefix = os.path.expanduser(prefix) if has_tilde else prefix

    # Extract directory and partial name
    if "/" in expanded_prefix or (os.sep in expanded_prefix and os.sep != "/"):
        dirname, partial = os.path.split(expanded_prefix)
        if not dirname:
            dirname = "/" if expanded_prefix.startswith("/") else "."
    else:
        dirname = "."
        partial = expanded_prefix

    base_path = Path(dirname)
    if not base_path.is_absolute() and root_dir:
        resolved_base = Path(root_dir) / base_path
    else:
        resolved_base = base_path

    if not resolved_base.exists() or not resolved_base.is_dir():
        return []

    items: list[CompletionItem] = []
    try:
        entries = sorted(
            resolved_base.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        )
    except (PermissionError, OSError):
        return []

    for entry in entries:
        name = entry.name
        # Skip hidden files unless user explicitly typed a leading dot in partial
        if name.startswith(".") and not partial.startswith("."):
            continue

        if name.lower().startswith(partial.lower()):
            is_dir = entry.is_dir()
            display_name = name + ("/" if is_dir else "")

            # Reconstruct completed path preserving user's prefix style
            if dirname == "." and not (prefix.startswith("./") or prefix.startswith(".\\")):
                completed_value = display_name
            else:
                if has_tilde and dirname.startswith(str(Path.home())):
                    rel_dir = os.path.relpath(dirname, str(Path.home()))
                    if rel_dir == ".":
                        completed_value = f"~/{display_name}"
                    else:
                        completed_value = f"~/{rel_dir}/{display_name}"
                else:
                    completed_value = os.path.join(dirname, display_name)

            desc = "dir" if is_dir else (entry.suffix.lstrip(".") or "file")
            items.append(
                CompletionItem(
                    value=completed_value,
                    display=display_name,
                    description=desc,
                    is_path=True,
                    is_dir=is_dir,
                )
            )

    return items[:30]


def find_common_prefix(strings: list[str]) -> str:
    """Find the longest common prefix among strings (case-sensitive)."""
    if not strings:
        return ""
    prefix = strings[0]
    for s in strings[1:]:
        while not s.startswith(prefix) and prefix:
            prefix = prefix[:-1]
        if not prefix:
            break
    return prefix


class CompletionMenu(VerticalScroll):
    """Floating menu showing matching completions above the input bar."""

    DEFAULT_CSS = f"""
    CompletionMenu {{
        width: auto;
        min-width: 32;
        max-width: 90;
        height: auto;
        max-height: {_MAX_VISIBLE_ITEMS + 2};
        background: rgb(20, 16, 32);
        border: round rgb(0, 240, 240);
        padding: 0 1;
        color: rgb(220, 220, 220);
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
        self._matches: list[CompletionItem] = []
        self._highlight_index = 0
        self._menu_text: Text = Text()
        # Signature: (cmd: str, arg_prefix: str) -> list[str | CompletionItem]
        self._subcommand_completer: (
            Callable[[str, str], list[str | CompletionItem]] | None
        ) = None
        self._working_dir: str | Path | None = None

        # Theme color overrides (can be updated via set_theme)
        self._color_primary = "#00f0f0"
        self._color_secondary = "#b48cff"
        self._color_background = "#141020"
        self._color_foreground = "#dcdcdc"
        self._color_dim = "#787887"

    def compose(self) -> ComposeResult:
        yield self._content

    # -- Theme configuration ----------------------------------------------------

    def set_theme_colors(
        self,
        primary: str | None = None,
        secondary: str | None = None,
        surface: str | None = None,
        foreground: str | None = None,
        dim: str | None = None,
    ) -> None:
        """Update colors to match the active theme."""
        from clanker.config.theme import hex_to_rgb, rgb_to_hex
        def _to_clean_hex(c: str) -> str:
            if c.startswith("#") and (len(c) == 4 or len(c) == 7):
                return c
            return rgb_to_hex(*hex_to_rgb(c))

        if primary:
            self._color_primary = _to_clean_hex(primary)
        if secondary:
            self._color_secondary = _to_clean_hex(secondary)
        if surface:
            self._color_background = _to_clean_hex(surface)
        if foreground:
            self._color_foreground = _to_clean_hex(foreground)
        if dim:
            self._color_dim = _to_clean_hex(dim)

        self.styles.border = ("round", self._color_primary)
        self.styles.background = self._color_background
        self.styles.color = self._color_foreground
        if self._matches:
            self._build_render()

    def set_working_dir(self, directory: str | Path | None) -> None:
        """Set working directory for filesystem path completions."""
        self._working_dir = directory

    def set_subcommand_completer(
        self, completer: Callable[[str, str], list[str | CompletionItem]]
    ) -> None:
        """Set a dynamic completer for subcommand arguments."""
        self._subcommand_completer = completer

    # -- Candidate Computation --------------------------------------------------

    def compute_matches(self, text: str, cursor_position: int | None = None) -> list[CompletionItem]:
        """Compute matching completion items for the text up to cursor."""
        text_before_cursor = text[:cursor_position] if cursor_position is not None else text

        # 1. Slash command argument completion: e.g. "/model claude" or "/effort hi"
        if text_before_cursor.startswith("/"):
            parts = text_before_cursor.split(maxsplit=1)
            cmd = parts[0].lower()
            has_space = " " in text_before_cursor

            if has_space:
                arg_prefix = parts[1] if len(parts) > 1 else ""
                if self._subcommand_completer:
                    raw_sub = self._subcommand_completer(cmd, arg_prefix)
                    items: list[CompletionItem] = []
                    for s in raw_sub:
                        if isinstance(s, CompletionItem):
                            items.append(s)
                        else:
                            items.append(
                                CompletionItem(
                                    value=f"{cmd} {s}",
                                    display=s,
                                    description="",
                                )
                            )
                    if items:
                        return items

                # Fallback path completion for commands taking paths (e.g. /import)
                if arg_prefix:
                    clean_path = arg_prefix.lstrip("@")
                    path_matches = complete_filepaths(clean_path, self._working_dir)
                    return [
                        CompletionItem(
                            value=f"{cmd} {m.value}",
                            display=m.display,
                            description=m.description,
                            is_path=True,
                            is_dir=m.is_dir,
                        )
                        for m in path_matches
                    ]
                return []

            # 2. Slash command name completion: e.g. "/re" -> "/reload", "/remember", "/resume"
            cmd_prefix = text_before_cursor.lower()
            matched_cmds = [c for c in self._all_commands if c.lower().startswith(cmd_prefix)]
            return [
                CompletionItem(
                    value=c,
                    display=c,
                    description=_COMMAND_DESCRIPTIONS.get(c, ""),
                )
                for c in matched_cmds
            ]

        # 3. Path completion (e.g. "@src/cl", "./src/", "tests/test_")
        # Extract the last token/word before cursor
        tokens = text_before_cursor.split()
        if not tokens and not text_before_cursor.endswith((" ", "\t")):
            return []

        # Target token is the current token being typed
        last_token = text_before_cursor.split()[-1] if not text_before_cursor.endswith(" ") else ""
        if not last_token:
            return []

        # Support @path or direct paths like src/ or ./ or ~/
        clean_path = last_token.lstrip("@")
        if (
            clean_path.startswith(("./", "../", "/", "~/", ".\\", "..\\"))
            or "/" in clean_path
            or "\\" in clean_path
            or last_token.startswith("@")
        ):
            path_matches = complete_filepaths(clean_path, self._working_dir)
            if last_token.startswith("@"):
                # Preserve the @ prefix for completion
                return [
                    CompletionItem(
                        value=f"@{m.value}",
                        display=f"@{m.display}",
                        description=m.description,
                        is_path=True,
                        is_dir=m.is_dir,
                    )
                    for m in path_matches
                ]
            return path_matches

        return []

    # -- Display & Navigation ---------------------------------------------------

    def show(self, matches: list[CompletionItem], highlight_index: int = 0) -> None:
        """Display the menu with the provided candidates."""
        self._matches = matches
        self._highlight_index = max(0, min(highlight_index, max(0, len(matches) - 1)))

        if not self._matches:
            self.hide()
            return

        self._build_render()
        self._position()
        self.add_class("visible")
        self._scroll_to_highlight()

    def hide(self) -> None:
        """Hide the completion menu."""
        self._matches = []
        self._highlight_index = 0
        self.remove_class("visible")

    @property
    def is_open(self) -> bool:
        return "visible" in self.classes and bool(self._matches)

    def next_item(self, wrap: bool = True) -> CompletionItem | None:
        """Select next item in the menu."""
        if not self._matches:
            return None
        if wrap:
            self._highlight_index = (self._highlight_index + 1) % len(self._matches)
        elif self._highlight_index < len(self._matches) - 1:
            self._highlight_index += 1
        self._build_render()
        self._scroll_to_highlight()
        self.refresh()
        return self.get_selected()

    def prev_item(self, wrap: bool = True) -> CompletionItem | None:
        """Select previous item in the menu."""
        if not self._matches:
            return None
        if wrap:
            self._highlight_index = (self._highlight_index - 1) % len(self._matches)
        elif self._highlight_index > 0:
            self._highlight_index -= 1
        self._build_render()
        self._scroll_to_highlight()
        self.refresh()
        return self.get_selected()

    def get_selected(self) -> CompletionItem | None:
        if self._matches and 0 <= self._highlight_index < len(self._matches):
            return self._matches[self._highlight_index]
        return None

    def get_matches(self) -> list[CompletionItem]:
        return list(self._matches)

    # -- Rendering Internals ----------------------------------------------------

    def _build_render(self) -> None:
        """Render the list of completion items with highlighted row and descriptions."""
        self._menu_text = Text()
        if not self._matches:
            self._content.update(self._menu_text)
            return

        max_display_len = max(len(m.display) for m in self._matches)
        for i, item in enumerate(self._matches):
            is_active = i == self._highlight_index
            prefix = "▶ " if is_active else "  "

            # Base item text
            row = Text()
            if is_active:
                row.append(prefix, style=f"bold {self._color_primary}")
                row.append(item.display, style=f"bold {self._color_primary}")
            else:
                row.append(prefix, style=self._color_dim)
                row.append(item.display, style=self._color_foreground)

            # Optional right-aligned description
            if item.description:
                padding = " " * (max_display_len - len(item.display) + 2)
                row.append(padding)
                desc_style = f"italic {self._color_secondary}" if is_active else f"dim {self._color_dim}"
                row.append(item.description, style=desc_style)

            self._menu_text.append_text(row)
            if i < len(self._matches) - 1:
                self._menu_text.append("\n")

        from contextlib import suppress

        with suppress(Exception):
            self._content.update(self._menu_text)

    def _scroll_to_highlight(self) -> None:
        """Keep the highlighted item in view."""
        line = self._highlight_index
        top = self.scroll_offset.y
        if line < top:
            self.scroll_to(y=line, animate=False)
        elif line >= top + _MAX_VISIBLE_ITEMS:
            self.scroll_to(y=line - _MAX_VISIBLE_ITEMS + 1, animate=False)

    def _position(self) -> None:
        """Position menu cleanly above the input area, never overlapping it."""
        if not self.is_attached:
            return
        screen = self.screen
        content_lines = min(len(self._matches), _MAX_VISIBLE_ITEMS)
        menu_height = content_lines + 2  # +2 for top & bottom border

        # Query input-area or prompt-bar region if mounted to place menu precisely above it
        input_top: int | None = None
        try:
            input_area = screen.query_one("#input-area")
            if input_area.is_attached and input_area.region.y > 0:
                input_top = input_area.region.y
        except Exception:
            pass

        if input_top is None:
            try:
                prompt_bar = screen.query_one("#prompt-bar")
                if prompt_bar.is_attached and prompt_bar.region.y > 0:
                    input_top = prompt_bar.region.y
            except Exception:
                pass

        if input_top is not None:
            # Sit flush directly on top of the input area boundary
            y = input_top - menu_height
        else:
            # Fallback based on typical 4-line bottom dock
            y = screen.size.height - 4 - menu_height

        if y < 1:
            y = 1
        self.offset = Offset(2, y)
