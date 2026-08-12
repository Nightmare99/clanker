"""Clanker Textual TUI Application."""

from __future__ import annotations

import asyncio
import base64
import itertools
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Input, Label, Static

from clanker.ui.chat_log import ChatLog, MessageType
from clanker.ui.clipboard_image import (
    ClipboardImage,
    clipboard_image_tool_available,
    read_clipboard_image,
)
from clanker.ui.status_bar import StatusBar
from clanker.ui.completion_menu import CompletionMenu
from clanker.ui.history_modal import HistoryScreen
from clanker.ui.subagent_history import SubagentHistoryScreen, SubagentRun

if TYPE_CHECKING:
    from clanker.config import Settings
    from clanker.ui.console import Console
    from clanker.ui.streaming import StreamResult

# ansi_shadow CLNKR — reads clearly, block style
_CLNKR_ART = r"""
  ██████╗██╗     ███╗   ██╗██╗  ██╗██████╗
 ██╔════╝██║     ████╗  ██║██║ ██╔╝██╔══██╗
 ██║     ██║     ██╔██╗ ██║█████╔╝ ██████╔╝
 ██║     ██║     ██║╚██╗██║██╔═██╗ ██╔══██╗
 ╚██████╗███████╗██║ ╚████║██║  ██╗██║  ██║
  ╚═════╝╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═╝
  """

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

_SLASH_COMMANDS = [
    "/clear", "/compact", "/config", "/copilot-login", "/exit", "/forget",
    "/help", "/history", "/list_memories", "/logs", "/memories", "/model",
    "/mcp", "/remember", "/restore", "/skill", "/workflow",
]


def _build_user_message_content(text: str, images: list[ClipboardImage]) -> str | list[dict]:
    """Build HumanMessage content, attaching any pasted images.

    Plain string when there are no images -- the common case, and the exact
    shape every other code path already expects. With images, switches to
    the standard multimodal content-block list (text block, then one
    image_url block per image as a base64 data URL) -- the same shape
    ``MultimodalToolResultsMiddleware`` already produces for tool results
    (see ``clanker/agent/middleware.py``), so summarization and the
    provider-facing request path handle a pasted image identically to one
    that came back from ``read_file``.
    """
    if not images:
        return text

    content: list[dict] = [{"type": "text", "text": text}]
    for image in images:
        b64_data = base64.b64encode(image.data).decode("utf-8")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{image.mime_type};base64,{b64_data}"},
        })
    return content


def _remove_nth_matching(items: list[tuple[str, Any]], key: str, n: int) -> list[tuple[str, Any]]:
    """Return *items* with its nth (0-indexed) ``key``-matching entry dropped.

    Used to forget one specific pasted-content entry out of
    ``_pending_pastes``/``_pending_images`` when its placeholder text isn't
    unique (e.g. two "[pasted 2 lines]" pastes) -- removing "the nth match"
    rather than "the first match" or "all matches" is what lets each
    occurrence in the input text map back to the paste it actually came
    from.
    """
    result = []
    seen = 0
    for item_key, value in items:
        if item_key == key:
            if seen == n:
                seen += 1
                continue
            seen += 1
        result.append((item_key, value))
    return result


class PromptInput(Input):
    """Input widget with Tab completion menu and Alt+Up/Down history navigation."""

    can_focus_within = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._history: list[str] = []
        self._history_index: int = -1
        self._saved_input: str = ""
        self._completion_menu: CompletionMenu | None = None
        self._menu_active = False
        # True once the user has explicitly taken keyboard control of the menu
        # (via Tab). Until then the menu is only a visual hint — Up/Down/Enter
        # keep their normal behavior (history nav / submit).
        self._menu_engaged = False
        # Cursor offset at the moment Tab was pressed, so we can restore it
        self._tab_cursor_offset: int = 0
        # Tracks previous value so watch_value can detect the "/" transition
        self._previous_value: str = ""
        self._on_history_add: callable | None = None
        # Multi-line pastes: Input is strictly single-line, so a pasted block
        # is collapsed to a "[pasted N lines]" placeholder in the visible
        # value, and the real text is stashed here (in placeholder-insertion
        # order) until submission, when pop_expanded_value() swaps it back in.
        self._pending_pastes: list[tuple[str, str]] = []
        # Pasted images: bracketed paste can't carry image bytes at all, so
        # these come from a fallback OS-clipboard check (see _on_paste /
        # action_paste), shown as a "[Image #N]" placeholder the same way.
        self._pending_images: list[tuple[str, ClipboardImage]] = []
        self._image_counter = 0
        # Shown once per session so a missing clipboard tool doesn't warn on
        # every empty paste (most of which are just an empty clipboard).
        self._warned_no_clipboard_tool = False

    def set_completion_menu(self, menu: CompletionMenu) -> None:
        self._completion_menu = menu

    def set_history(self, history: list[str]) -> None:
        """Set app-scoped history (loaded from file)."""
        self._history = list(history)
        self._history_index = -1

    def set_history_add_callback(self, callback: callable) -> None:
        """Set callback invoked when a new item is added to history."""
        self._on_history_add = callback

    # -- key handling ----------------------------------------------------------

    def on_key(self, event) -> None:
        key = event.key

        # Tab: activate / cycle / accept completion
        if key == "tab":
            self._on_tab()
            event.stop()
            return

        # While menu is active AND engaged (user pressed Tab to take control) …
        if self._menu_active and self._menu_engaged and self._completion_menu:
            if key == "enter":
                selected = self._completion_menu.get_selected()
                if selected:
                    self._accept_completion(selected)
                    event.stop()
                    return
            elif key == "up":
                self._completion_menu.prev_item()
                event.stop()
                return
            elif key == "down":
                self._completion_menu.next_item()
                event.stop()
                return
            elif key == "escape":
                self._hide_menu()
                event.stop()
                return
            # Printable keys, backspace, delete — let the Input widget handle
            # them normally so the text updates; watch_value will re-filter
            # the menu afterward.

        # Up / Down (and Alt+Up / Alt+Down): history navigation when menu is closed
        if key in ("up", "m-up"):
            self._navigate_history(-1)
            event.stop()
            return
        if key in ("down", "m-down"):
            self._navigate_history(1)
            event.stop()
            return

        # Plain Escape (no menu): clear input
        if key == "escape":
            self.value = ""
            self._pending_pastes = []
            self._pending_images = []
            self._image_counter = 0
            event.stop()

    # -- paste handling ----------------------------------------------------------

    def _on_paste(self, event: events.Paste) -> None:
        """Collapse a multi-line paste to a placeholder instead of losing all but line 1.

        Textual's ``Input`` is strictly single-line -- its default paste
        handler (``Input._on_paste``) takes only ``event.text.splitlines()[0]``
        and silently drops the rest, since embedded newlines can't render
        sanely in a height-1 field. Rather than lose the pasted content, a
        multi-line paste is shown as a single ``[pasted N lines]`` token and
        the real text is stashed in ``_pending_pastes``, swapped back in by
        ``pop_expanded_value()`` when the input is actually submitted.

        ``event.prevent_default()`` is required here, not just ``event.stop()``:
        Textual dispatches same-named handlers across the *entire* class MRO,
        not just the most-derived override, so without it ``Input``'s own
        ``_on_paste`` would ALSO run right after ours -- inserting its
        first-line-only text a second time at the cursor we just advanced
        past the placeholder. ``prevent_default()`` is the documented way to
        suppress those base-class handlers; ``stop()`` only suppresses
        bubbling to the parent widget, a separate mechanism.
        """
        if not event.text:
            # Bracketed paste has no text to deliver -- either the clipboard
            # is genuinely empty, or (since bracketed paste can't carry
            # binary data at all) it holds an image and the terminal forwarded
            # an empty paste rather than nothing. Check the OS clipboard
            # directly rather than assume either way.
            self._start_clipboard_image_check()
            return

        event.prevent_default()

        lines = event.text.splitlines()
        if len(lines) <= 1:
            super()._on_paste(event)
            return

        event.stop()
        placeholder = f"[pasted {len(lines)} lines]"
        # Normalize to "\n" -- terminals vary in what they actually send for
        # line breaks in a bracketed paste (e.g. bare "\r"), and Rich's Text
        # (which renders the expanded message in the chat log) only treats
        # "\n" as a line break. Left un-normalized, other separators render
        # as nothing or as a stray control character instead of a new line,
        # squashing the whole paste onto one visual line.
        self._pending_pastes.append((placeholder, "\n".join(lines)))

        selection = self.selection
        if selection.is_empty:
            self.insert_text_at_cursor(placeholder)
        else:
            self.replace(placeholder, *selection)

    def pop_expanded_value(self) -> tuple[str, list[ClipboardImage]]:
        """Return (text with paste placeholders expanded, pending images in order).

        Clears both ``_pending_pastes`` and ``_pending_images`` -- meant to
        be called once, right before the input is actually sent (submitted
        or queued), not for display. "[Image #N]" placeholders are left in
        the returned text as-is (they read fine as a label); the images
        themselves come back separately since they can't be spliced into a
        plain string.
        """
        text = self.value
        for placeholder, full_text in self._pending_pastes:
            text = text.replace(placeholder, full_text, 1)
        self._pending_pastes = []

        images = [image for _placeholder, image in self._pending_images]
        self._pending_images = []
        self._image_counter = 0
        return text, images

    # -- atomic placeholder deletion ---------------------------------------------

    def action_delete_left(self) -> None:
        """Backspace: delete a pending placeholder as one block, not char-by-char.

        A "[pasted N lines]"/"[Image #N]" token stands in for content that
        isn't meaningfully editable a character at a time -- eating into it
        would corrupt the placeholder text so it no longer matches what
        ``pop_expanded_value`` looks for, silently leaving mangled text in
        the sent message instead of either fully keeping or fully dropping
        the paste. When the cursor overlaps a still-pending placeholder,
        this removes the whole token (and forgets the paste/image it stood
        for) in one keystroke instead.
        """
        if self.selection.is_empty:
            span = self._placeholder_span_at_cursor(edge="left")
            if span is not None:
                start, end, placeholder = span
                self._forget_placeholder_occurrence(placeholder, start)
                self.delete(start, end)
                return
        super().action_delete_left()

    def action_delete_right(self) -> None:
        """Delete (forward): same atomic-placeholder handling as action_delete_left."""
        if self.selection.is_empty:
            span = self._placeholder_span_at_cursor(edge="right")
            if span is not None:
                start, end, placeholder = span
                self._forget_placeholder_occurrence(placeholder, start)
                self.delete(start, end)
                return
        super().action_delete_right()

    def _all_placeholder_texts(self) -> list[str]:
        return [ph for ph, _ in self._pending_pastes] + [ph for ph, _ in self._pending_images]

    def _placeholder_span_at_cursor(self, edge: str) -> tuple[int, int, str] | None:
        """Find a pending placeholder overlapping the cursor for a delete in *edge* direction.

        ``edge="left"`` (backspace) matches when the cursor sits anywhere
        from just past the placeholder's start through its end -- i.e. the
        common case (cursor right after it) plus the cursor having been
        moved into its middle via the arrow keys. ``edge="right"`` (forward
        delete) is the mirror: start through just before the end.
        """
        pos = self.cursor_position
        text = self.value
        for placeholder in self._all_placeholder_texts():
            search_from = 0
            while True:
                idx = text.find(placeholder, search_from)
                if idx == -1:
                    break
                end = idx + len(placeholder)
                if edge == "left" and idx < pos <= end:
                    return idx, end, placeholder
                if edge == "right" and idx <= pos < end:
                    return idx, end, placeholder
                search_from = idx + 1
        return None

    def _forget_placeholder_occurrence(self, placeholder: str, start: int) -> None:
        """Drop the pending paste/image for the placeholder occurrence starting at *start*.

        The same placeholder text can appear more than once (e.g. two
        "[pasted 2 lines]" pastes) -- ``_pending_pastes``/``_pending_images``
        are ordered lists matching left-to-right text occurrence order (the
        same assumption ``pop_expanded_value`` relies on), so counting how
        many occurrences of this placeholder appear before *start* picks out
        the exact matching entry rather than an arbitrary one.
        """
        occurrence_index = self.value[:start].count(placeholder)
        self._pending_pastes = _remove_nth_matching(
            self._pending_pastes, placeholder, occurrence_index
        )
        self._pending_images = _remove_nth_matching(
            self._pending_images, placeholder, occurrence_index
        )

    # -- image paste (OS clipboard fallback) ------------------------------------

    def action_paste(self) -> None:
        """Ctrl+V: Input's own binding, overridden to add an image fallback.

        The base implementation pastes from Textual's *internal* text
        clipboard (``self.app.clipboard``), which is only ever populated by
        an explicit in-app copy -- it's empty by default. An empty clipboard
        here is also what you'd see if the terminal swallowed Ctrl+V for its
        own OS-level paste and simply sent nothing (no ``Paste`` event at
        all) because the OS clipboard held an image with no text
        representation. Either way, an empty internal clipboard is worth a
        check for an image before doing nothing.
        """
        if not self.app.clipboard:
            self._start_clipboard_image_check()
            return
        super().action_paste()

    def _start_clipboard_image_check(self) -> None:
        self.run_worker(self._try_paste_image(), exclusive=False, group="clipboard-image")

    async def _try_paste_image(self) -> None:
        """Best-effort: look for an image on the OS clipboard.

        Runs the (subprocess-based) clipboard read off the event loop so a
        slow/hanging clipboard tool can't freeze the UI.
        """
        loop = asyncio.get_running_loop()
        image = await loop.run_in_executor(None, read_clipboard_image)

        if image is None:
            if not self._warned_no_clipboard_tool and not clipboard_image_tool_available():
                self._warned_no_clipboard_tool = True
                self.notify(
                    "Image paste isn't available on this system -- install "
                    "xclip (X11) or wl-clipboard (Wayland) to enable it.",
                    severity="warning",
                    timeout=6,
                )
            return

        self._image_counter += 1
        placeholder = f"[Image #{self._image_counter}]"
        self._pending_images.append((placeholder, image))

        selection = self.selection
        if selection.is_empty:
            self.insert_text_at_cursor(placeholder)
        else:
            self.replace(placeholder, *selection)

    # -- auto-show menu on "/" transition --------------------------------------

    def watch_value(self, value: str) -> None:
        """Show (or re-filter) the completion menu when input starts with '/'.

        Fires on the initial "/" transition and then keeps the menu in sync
        whenever the menu is already open — without consuming the key event
        so the Input widget still processes every keystroke normally.
        """
        prev = self._previous_value
        self._previous_value = value

        if not value.startswith("/"):
            if self._menu_active and self._completion_menu:
                self._hide_menu()
            return

        # Case 1: just typed "/" — open the menu
        if not prev.startswith("/"):
            if self._completion_menu and not self._menu_active:
                self._completion_menu.show(value)
                if self._completion_menu._matches:
                    self._menu_active = True
        # Case 2: menu already open — re-filter to match edited text
        elif self._menu_active and self._completion_menu:
            self._completion_menu.show(value, engaged=self._menu_engaged)

    # -- tab completion --------------------------------------------------------

    def _on_tab(self) -> None:
        text = self.value
        if not text or not text.startswith("/"):
            return

        if not self._completion_menu:
            # Fallback: inline completion without menu
            self._tab_inline()
            return

        # Record cursor position so we can restore relative position
        self._tab_cursor_offset = self.cursor_position

        if self._menu_active and self._menu_engaged:
            # Menu already engaged — accept highlighted item
            selected = self._completion_menu.get_selected()
            if selected:
                self._accept_completion(selected)
            return

        # Menu may already be visible (auto-shown on "/"), but not yet engaged.
        if not self._menu_active:
            self._completion_menu.show(text, engaged=True)
        else:
            self._completion_menu.set_engaged(True)

        if self._completion_menu._matches:
            self._menu_active = True
            self._menu_engaged = True

    def _tab_inline(self) -> None:
        """Inline completion fallback when no menu is wired."""
        text = self.value
        matches = [c for c in _SLASH_COMMANDS if c.startswith(text)]
        if matches:
            self.value = matches[0]
            self.cursor_position = len(matches[0])

    def _accept_completion(self, completion: str) -> None:
        """Replace the pre-cursor text with the completion, restore cursor offset."""
        cursor = self._tab_cursor_offset
        before = self.value[:cursor]
        after = self.value[cursor:]
        self.value = completion + after
        self.cursor_position = len(completion) + len(after)
        self._hide_menu()

    def _hide_menu(self) -> None:
        if self._menu_active and self._completion_menu:
            self._menu_active = False
            self._menu_engaged = False
            self._completion_menu.hide()

    # -- history navigation (Alt+Up / Alt+Down) --------------------------------

    def _navigate_history(self, direction: int) -> None:
        if not self._history:
            return
        self._hide_menu()
        if direction < 0:
            if self._history_index == -1:
                self._saved_input = self.value
            next_idx = self._history_index + 1
            if next_idx < len(self._history):
                self._history_index = next_idx
                self.value = self._history[len(self._history) - 1 - self._history_index]
                self.cursor_position = len(self.value)
        else:
            if self._history_index <= 0:
                self._history_index = -1
                self.value = self._saved_input
                self._saved_input = ""
                self.cursor_position = len(self.value)
                return
            self._history_index -= 1
            self.value = self._history[len(self._history) - 1 - self._history_index]
            self.cursor_position = len(self.value)

    def add_to_history(self, text: str) -> None:
        if text.strip():
            self._history.append(text.strip())
            self._history_index = -1
            if self._on_history_add:
                self._on_history_add(text.strip())


class MessageQueue(Static):
    """Shows messages queued while the agent is processing, above the input bar."""

    DEFAULT_CSS = """
    MessageQueue {
        dock: bottom;
        background: black;
        color: rgb(150, 150, 150);
        padding: 0 1;
        display: none;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._entries: list[tuple[str, bool]] = []  # (text, picked_up)

    def add_pending(self, text: str) -> None:
        self._entries.append((text, False))
        self._refresh()

    def mark_all_picked_up(self) -> None:
        self._entries = [(text, True) for text, _ in self._entries]
        self._refresh()
        self.set_timer(1.5, self._clear_if_all_picked_up)

    def _clear_if_all_picked_up(self) -> None:
        if all(picked for _, picked in self._entries):
            self.clear()

    def clear(self) -> None:
        self._entries = []
        self._refresh()

    def _refresh(self) -> None:
        if not self._entries:
            self.display = False
            self.update("")
            return
        self.display = True
        lines = []
        for text, picked in self._entries:
            mark = "✓" if picked else "⏳"
            preview = text if len(text) <= 80 else text[:77] + "..."
            lines.append(f"{mark} {preview}")
        self.update("\n".join(lines))


class TodoPanel(Static):
    """Pinned checklist of the agent's current plan, docked above the input bar.

    Mirrors MessageQueue's dock/hide pattern above: hidden (``display: none``)
    until ``todo_write``/``todo_read`` puts at least one item on the board,
    and hidden again once every item is completed (or the list is cleared)
    so it doesn't linger as clutter once the work is actually done.
    """

    DEFAULT_CSS = """
    TodoPanel {
        dock: bottom;
        background: black;
        color: rgb(180, 180, 180);
        padding: 0 1;
        display: none;
        max-height: 10;
    }
    """

    # Bounded so a long plan can't eat the whole screen -- overflow items
    # collapse into a "+N more" line (see tool_summary.build_todo_checklist_text).
    MAX_VISIBLE_ITEMS = 8

    def set_todos(self, todos: list[dict]) -> None:
        """Refresh the panel from a todo_write/todo_read result's `todos` list.

        Hides the panel when there's nothing to show (empty list) or nothing
        left to do (every item completed).
        """
        if not todos or all(t.get("status") == "completed" for t in todos):
            self.display = False
            return

        from clanker.ui import tool_summary

        text = tool_summary.build_todo_checklist_text(
            todos, indent=" ", max_items=self.MAX_VISIBLE_ITEMS
        )
        self.update(text if text is not None else Text(""))
        self.display = True


class PromptBar(Horizontal):
    """Bottom input bar with > prompt symbol, Input widget, and completion menu."""

    DEFAULT_CSS = """
    PromptBar {
        height: 1;
        dock: bottom;
        background: black;
        padding: 0;
    }

    PromptBar #prompt-symbol {
        color: rgb(0, 240, 240);
        width: 2;
    }

    PromptBar #prompt-input {
        width: 1fr;
        border: none;
        background: black;
        color: rgb(200, 200, 200);
        padding: 0;
    }

    PromptBar #prompt-input:focus {
        border: none;
        background: black;
        color: rgb(200, 200, 200);
    }

    PromptBar #prompt-input:hover {
        border: none;
        background: black;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label(">", id="prompt-symbol")
        yield PromptInput(
            placeholder="Type your message... (ctrl+c interrupt)",
            id="prompt-input",
        )


class ClankerApp(App):
    """Main Textual application for Clanker."""

    CSS_PATH = str(Path(__file__).parent / "styles.tcss")

    BINDINGS = [
        # Priority so this always wins over Input's own "ctrl+c: copy selection
        # within the field" binding and Screen's silent built-in copy binding —
        # both would otherwise pre-empt this action with no user feedback.
        Binding("ctrl+c", "copy_or_interrupt", "Copy/Interrupt", show=True, priority=True),
        Binding("ctrl+d", "quit", "Quit", show=True),
        Binding("f2", "show_subagents", "Subagents", show=True),
        Binding("f3", "show_history", "History", show=True),
    ]

    def __init__(
        self,
        console: Console,
        model_info: str = "",
        update_info: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.clanker_console = console
        self.interrupt_requested = False
        self._interrupt_event = asyncio.Event()
        self._model_info = model_info
        self._update_info = update_info
        self._processing = False
        self._input_history: list[str] = self._load_history()
        self._input_queue: asyncio.Queue[str] = asyncio.Queue()
        # Subagent runs from the current (or most recently completed) turn —
        # reset when a new turn starts, so F2 always shows "this turn's" runs.
        self._subagent_runs: list[SubagentRun] = []

    def _load_history(self) -> list[str]:
        """Load input history from file across sessions."""
        try:
            history_file = Path.home() / ".clanker" / "input_history.txt"
            if history_file.exists():
                lines = history_file.read_text().strip().split("\n")
                return [l for l in lines if l.strip()][-500:]
        except OSError:
            pass
        return []

    def _save_history(self) -> None:
        """Persist input history to file."""
        try:
            history_file = Path.home() / ".clanker" / "input_history.txt"
            history_file.parent.mkdir(parents=True, exist_ok=True)
            history_file.write_text("\n".join(self._input_history[-500:]) + "\n")
        except OSError:
            pass

    def compose(self) -> ComposeResult:
        yield ChatLog(id="chat-log")
        yield StatusBar(id="status-bar")
        yield MessageQueue(id="message-queue")
        yield TodoPanel(id="todo-panel")
        yield PromptBar(id="prompt-bar")
        yield CompletionMenu(_SLASH_COMMANDS)

    def on_mount(self) -> None:
        prompt_input = self.query_one("#prompt-input", PromptInput)
        prompt_input.focus()
        prompt_input.set_history(self._input_history)
        prompt_input.set_history_add_callback(self._on_input_history_add)

        # Wire completion menu to input
        menu = self.query_one("#completion-menu", CompletionMenu)
        prompt_input.set_completion_menu(menu)
        menu.set_subcommand_completer(self._complete_subcommand)

        chat_log = self.get_chat_log()

        self.run_worker(self._play_hero(chat_log))

    async def _play_hero(self, chat_log: ChatLog) -> None:
        """Play the hero animation inside the chat log — persists after reveal.

        The update banner (if any) is mounted right after, so it lands below
        the ASCII art rather than above it.
        """
        from clanker.runtime import is_yolo_mode

        art_lines = _CLNKR_ART.split("\n")
        spinner = itertools.cycle(_SPINNER_FRAMES)

        for i in range(1, len(art_lines) + 1):
            partial = "\n".join(art_lines[:i])
            chat_log.update_hero_art(partial)
            await asyncio.sleep(0.08)

        for _ in range(6):
            frame = next(spinner)
            chat_log.update_hero_art(_CLNKR_ART, init_text=f"  {frame} Initializing subsystems...")
            await asyncio.sleep(0.12)

        chat_log.update_hero_final(
            art=_CLNKR_ART,
            model_info=self._model_info,
            yolo_mode=is_yolo_mode(),
        )

        if self._update_info:
            chat_log.add_update_banner(
                current=self._update_info["current"],
                latest=self._update_info["latest"],
                install_cmd=self._update_info["install_cmd"],
            )

    # --- Widget accessors ---

    def get_chat_log(self) -> ChatLog:
        return self.query_one("#chat-log", ChatLog)

    def get_status_bar(self) -> StatusBar:
        return self.query_one("#status-bar", StatusBar)

    def get_todo_panel(self) -> TodoPanel:
        return self.query_one("#todo-panel", TodoPanel)

    def get_prompt_input(self) -> PromptInput:
        return self.query_one("#prompt-input", PromptInput)

    def get_message_queue(self) -> MessageQueue:
        return self.query_one("#message-queue", MessageQueue)

    # --- Actions ---

    def _on_input_history_add(self, text: str) -> None:
        self._input_history.append(text)
        self._save_history()
        prompt_input = self.get_prompt_input()
        prompt_input.set_history(self._input_history)

    def action_copy_or_interrupt(self) -> None:
        """Copy selected text if any, otherwise interrupt the agent.

        Checks the focused Input's own in-field selection first (its own
        cursor-based selection system), then the screen-wide mouse-drag
        selection, before falling back to interrupting the agent.
        """
        focused = self.focused
        input_selection = (
            focused.selected_text if isinstance(focused, Input) else None
        )
        selected_text = input_selection or self.screen.get_selected_text()
        if selected_text:
            self.copy_to_clipboard(selected_text)
            self.notify(f"Copied {len(selected_text)} characters", severity="information")
        else:
            self.action_interrupt()

    def action_interrupt(self) -> None:
        from clanker.ui.streaming import _cancel_streaming_task

        self.interrupt_requested = True
        self._interrupt_event.set()
        _cancel_streaming_task()

    def action_quit(self) -> None:
        self._save_history()
        self.exit()

    def action_show_subagents(self) -> None:
        # Pass the live list (not a copy) so runs spawned or updated while
        # the popup is open show up via its polling refresh.
        self.push_screen(SubagentHistoryScreen(self._subagent_runs))

    def action_show_history(self) -> None:
        self.push_screen(HistoryScreen(self._conversation_messages))

    def register_subagent_run(self, run: SubagentRun) -> None:
        """Track a newly spawned subagent run and refresh the status bar hint."""
        self._subagent_runs.append(run)
        self.refresh_subagent_hint()

    def refresh_subagent_hint(self) -> None:
        """Update the status bar's subagent count/running indicator."""
        try:
            running = sum(1 for r in self._subagent_runs if r.status == "running")
            self.get_status_bar().set_subagent_runs(running, len(self._subagent_runs))
        except Exception:
            pass

    def reset_interrupt(self) -> None:
        from clanker.ui.streaming import reset_interrupted

        self.interrupt_requested = False
        self._interrupt_event.clear()
        reset_interrupted()

    def add_subagent_tokens(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> None:
        """Accumulate subagent tokens and cost into the session tracker.

        Subagent has its own context window, so tokens do not affect the
        parent's context remaining. But we accumulate input/output tokens
        and cost so the status bar shows accurate session totals.
        """
        try:
            from clanker.config import get_default_model

            token_tracker = self._token_tracker
            cm = get_default_model()
            if cm:
                turn_cost = cm.compute_cost(
                    input_tokens,
                    output_tokens,
                    cache_read_tokens,
                    cache_creation_tokens,
                )
            else:
                turn_cost = None
            # Accumulate token counts and cost
            token_tracker.total_input += input_tokens
            token_tracker.total_output += output_tokens
            if turn_cost is not None:
                token_tracker.total_cost_usd = (
                    (token_tracker.total_cost_usd or 0.0) + turn_cost
                )
            # Refresh the status bar to show updated totals
            try:
                from clanker.config import get_settings
                settings = get_settings()
                if settings.output.show_token_usage:
                    status_bar = self.get_status_bar()
                    status_bar.set_token_usage(
                        token_tracker.total_input,
                        token_tracker.total_output,
                        token_tracker.context_remaining_percent,
                        token_tracker.total_cost_usd,
                    )
            except Exception:
                pass
        except Exception:
            pass

    # --- Input handling ---

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        prompt_input = self.get_prompt_input()

        # History/recall keep the placeholder form -- Input can't safely
        # redisplay embedded newlines -- while everything actually sent to
        # the agent/chat log gets the real pasted text/images swapped back in.
        raw = prompt_input.value.strip()
        if not raw:
            return
        text, images = prompt_input.pop_expanded_value()
        text = text.strip()

        prompt_input.add_to_history(raw)
        prompt_input.value = ""

        if self._processing and not text.startswith("/"):
            if images:
                # The follow-up queue only carries plain text today (see
                # streaming.py's on_chat_model_start handling) -- rather
                # than silently drop the image, say so; the "[Image #N]"
                # label stays in the sent text either way, so at least it's
                # visible that something was left out.
                self.get_chat_log().add_message(
                    "Pasted image(s) can't be attached to a queued follow-up "
                    "yet -- sending the text only. Wait for the current turn "
                    "to finish to attach an image.",
                    MessageType.WARNING,
                )
            self._input_queue.put_nowait(text)
            self._add_user_message_to_ui(text)
            self.get_message_queue().add_pending(text)
            return

        cmd_result = self._handle_slash_command(text)
        if cmd_result is not None:
            if cmd_result == "exit":
                self.exit()
            elif cmd_result == "skip":
                pass
            else:
                self._set_processing(True)
                self._add_user_message_to_ui(cmd_result)
                self.run_worker(self._run_agent(cmd_result), exclusive=True)
            return

        self._set_processing(True)
        self._add_user_message_to_ui(text)
        self.run_worker(self._run_agent(text, images), exclusive=True)

    def _add_user_message_to_ui(self, text: str) -> None:
        chat_log = self.get_chat_log()
        chat_log.add_message(text, MessageType.USER)

    def _set_processing(self, processing: bool) -> None:
        self._processing = processing
        prompt_input = self.get_prompt_input()
        prompt_input.disabled = False
        prompt_input.placeholder = (
            "Type a follow-up... (queued until agent's next step)"
            if processing
            else "Type your message... (ctrl+c interrupt)"
        )
        if not processing:
            prompt_input.focus()
            self.get_message_queue().clear()

    def _handle_slash_command(self, text: str) -> str | None:
        if not text.startswith("/"):
            return None

        if text.strip().lower() == "/copilot-login":
            # Runs in a background worker instead of through handle_command's
            # blocking poll loop -- that loop runs on the same thread as the
            # UI event loop, so a time.sleep()-based wait would freeze the
            # entire TUI for however long the user takes to approve in their
            # browser (often well over a minute).
            self.run_worker(
                self._copilot_login_flow(), exclusive=True, group="copilot-login"
            )
            return "skip"

        from clanker.cli import handle_command

        console = self.clanker_console
        session_manager = self._session_manager
        conversation_messages = self._conversation_messages
        chat_log = self.get_chat_log()

        result = handle_command(
            text, console, session_manager, conversation_messages, chat_log
        )
        if result == "exit":
            return "exit"
        if result and result.startswith("restore:"):
            session_id = result.split(":", 1)[1]
            messages = session_manager.get_session_messages(session_id)
            if messages:
                if conversation_messages:
                    session_manager.save_conversation_snapshot(conversation_messages)
                session_manager.resume_session(session_id)
                # Mutate in place rather than rebinding -- `conversation_messages`
                # is the SAME list object as `self._conversation_messages`, which
                # `_run_agent` keeps appending to and using for future snapshot
                # saves, and which the history modal (F3) reads directly. A
                # rebind here would silently drop the restored history from both.
                conversation_messages.clear()
                conversation_messages.extend(messages)
                self._pending_restore_messages = list(messages)
                chat_log.add_message(
                    f"Restored session {session_id} with {len(messages)} messages",
                    MessageType.INFO,
                )
            else:
                chat_log.add_message(
                    f"Session {session_id} not found", MessageType.WARNING
                )
            return "skip"
        if result and (result.startswith("workflow:") or result.startswith("skill:")):
            return result.split(":", 1)[1]
        if result is None or result == "":
            return "skip"
        return "skip"

    # --- Agent execution ---

    async def _run_agent(
        self, user_input: str, images: list[ClipboardImage] | None = None
    ) -> None:
        from langchain_core.messages import AIMessage, HumanMessage

        from clanker.config import get_default_model
        from clanker.logging import get_logger
        from clanker.ui.streaming import stream_agent_response_async

        self.reset_interrupt()
        self._subagent_runs = []
        self.refresh_subagent_hint()

        logger = get_logger("tui")

        console = self.clanker_console
        settings: Settings = self._settings
        session_manager = self._session_manager
        conversation_messages = self._conversation_messages
        pending_restore_messages = self._pending_restore_messages
        token_tracker = self._token_tracker
        working_dir = self._working_dir

        chat_log = self.get_chat_log()
        status_bar = self.get_status_bar()

        user_msg = HumanMessage(content=_build_user_message_content(user_input, images or []))
        conversation_messages.append(user_msg)

        if pending_restore_messages:
            turn_messages = [*pending_restore_messages, user_msg]
            self._pending_restore_messages = []
        else:
            turn_messages = [user_msg]

        state = {
            "messages": turn_messages,
            "working_directory": working_dir,
        }

        console._textual_app = self

        try:
            logger.info("Processing user message: %s", user_input[:100])

            result: StreamResult = await stream_agent_response_async(
                settings,
                session_manager.checkpointer,
                state,
                session_manager.get_config(),
                console,
                input_queue=self._input_queue,
            )

            if result.input_tokens > 0 or result.output_tokens > 0:
                cm = get_default_model()
                token_tracker.context_window = cm.max_input_tokens if cm else None
                turn_cost = cm.compute_cost(
                    result.input_tokens,
                    result.output_tokens,
                    result.cache_read_tokens,
                    result.cache_creation_tokens,
                ) if cm else None
                token_tracker.add_turn(
                    result.input_tokens,
                    result.output_tokens,
                    result.cache_read_tokens,
                    result.cache_creation_tokens,
                    turn_cost,
                )

            if result.response:
                conversation_messages.append(AIMessage(content=result.response))
                session_manager.save_conversation_snapshot(conversation_messages)
            else:
                logger.warning(
                    "Empty agent response. summarization=%s input=%d output=%d",
                    getattr(result, "summarization_occurred", "?"),
                    result.input_tokens,
                    result.output_tokens,
                )

            if result.summarization_occurred:
                from clanker.cli import sync_conversation_after_auto_compaction

                sync_conversation_after_auto_compaction(
                    conversation_messages, session_manager, settings, console, chat_log
                )

            if (
                result.input_tokens > 0
                or result.output_tokens > 0
            ) and settings.output.show_token_usage:
                status_bar.set_token_usage(
                    result.input_tokens,
                    result.output_tokens,
                    token_tracker.context_remaining_percent,
                    token_tracker.total_cost_usd,
                )

            chat_log.add_separator()
            logger.debug("Agent response completed successfully")

        except Exception as e:
            logger.exception("Agent error: %s", e)
            chat_log.add_message(f"Agent error: {e}", MessageType.ERROR)
        finally:
            self._set_processing(False)

    # --- Copilot device-code login ---

    async def _copilot_login_flow(self) -> None:
        """Run the GitHub Copilot device-code login without blocking the UI.

        Mirrors ``handle_command``'s ``/copilot-login`` branch (used by the
        non-TUI REPL, where blocking is harmless) but polls with
        ``asyncio.sleep`` and runs each blocking HTTP call via
        ``asyncio.to_thread`` so the rest of the app stays responsive while
        waiting for the user to approve the code in their browser. Ctrl+C
        sets the same interrupt event the agent-streaming path uses, so it
        doubles as "cancel this login".
        """
        from clanker.config.copilot_auth import (
            CopilotAuthError,
            complete_login,
            poll_for_github_token,
            start_device_flow,
            sync_copilot_models,
        )

        chat_log = self.get_chat_log()
        self.reset_interrupt()

        try:
            session = await asyncio.to_thread(start_device_flow)
        except CopilotAuthError as e:
            chat_log.add_message(str(e), MessageType.ERROR)
            return

        chat_log.add_message(
            f"Open {session.verification_uri} and enter code: {session.user_code}\n"
            "Waiting for approval... (Ctrl+C to cancel)",
            MessageType.INFO,
        )

        github_token: str | None = None
        try:
            while github_token is None:
                if self._interrupt_event.is_set():
                    chat_log.add_message("Login cancelled.", MessageType.WARNING)
                    return
                await asyncio.sleep(session.interval)
                github_token = await asyncio.to_thread(poll_for_github_token, session)
        except CopilotAuthError as e:
            chat_log.add_message(str(e), MessageType.ERROR)
            return
        finally:
            self.reset_interrupt()

        try:
            await asyncio.to_thread(complete_login, github_token)
            synced = await asyncio.to_thread(sync_copilot_models)
        except CopilotAuthError as e:
            chat_log.add_message(str(e), MessageType.ERROR)
            return

        chat_log.add_message(
            f"Connected! Synced {synced} Copilot model(s).\nUse /model to switch to one.",
            MessageType.SUCCESS,
        )

    # --- Subcommand completion ---

    def _complete_subcommand(self, cmd: str, arg_prefix: str) -> list[str]:
        """Return completions for a specific subcommand's arguments."""
        try:
            if cmd == "/model":
                from clanker.config import list_model_names
                completions = list_model_names()
            elif cmd == "/skill":
                from clanker.skills import list_skills
                completions = list(list_skills().keys())
            elif cmd == "/workflow":
                from clanker.workflows import list_workflows
                completions = list_workflows()
            elif cmd == "/restore":
                completions = []
                try:
                    sm = self._session_manager
                    for sess in sm.list_sessions():
                        completions.append(sess.get("id", ""))
                except Exception:
                    pass
            else:
                return []

            if arg_prefix:
                completions = [c for c in completions if arg_prefix.lower() in c.lower()]
            return completions
        except Exception:
            return []
