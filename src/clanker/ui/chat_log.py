"""Chat log widget - scrollable message history with tool rendering."""

from __future__ import annotations

import asyncio
import colorsys
import contextlib
import math
from dataclasses import dataclass, field
from enum import StrEnum

from rich.syntax import Syntax
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Markdown, Rule, Static

from clanker.config.theme import ColorPalette, HeroTheme, get_theme_config, hex_to_rgb, rgb_str
from clanker.ui import tool_summary
from clanker.ui.selection_screen import SelectionScreen


class MessageType(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    NOTIFY = "notify"
    ERROR = "error"
    INFO = "info"
    WARNING = "warning"
    SUCCESS = "success"


# Hero section colors
_CYAN = "rgb(0,240,240)"
_BLUE = "rgb(100,190,255)"
_GREEN = "rgb(180,255,60)"
_LIME = "rgb(180,255,60)"
_WHITE = "white"
_GREY = "rgb(100,100,100)"

# Cyan-to-blue gradient over the ASCII art banner: how fast the color shifts
# across columns/rows, and how far the phase advances per tick (see
# _HeroArt._gradient_style/_tick). Hue smoothly transitions between cyan and
# blue across the art banner. This gradient wash keeps looping for the whole session
# -- unlike the wave bounce below, it never settles -- since repainting it costs
# nothing beyond this one widget (see _HeroArt's docstring).
_CYAN_HUE = 0.5  # hue of cyan (180°) in colorsys's 0..1 scale
_BLUE_HUE = 2 / 3  # hue of blue (240°) in colorsys's 0..1 scale
_GRADIENT_SATURATION = 0.8
_GRADIENT_VALUE = 1.0
_GRADIENT_COL_STEP = 0.02
_GRADIENT_ROW_STEP = 0.06
_GRADIENT_PHASE_STEP = 0.02

# Backwards compatibility aliases
_LIME_HUE = _CYAN_HUE
_LIME_SATURATION = _GRADIENT_SATURATION
_LIME_MIN_VALUE = 0.55
_LIME_MAX_VALUE = 1.0
_LIME_COL_STEP = _GRADIENT_COL_STEP
_LIME_ROW_STEP = _GRADIENT_ROW_STEP
_LIME_PHASE_STEP = _GRADIENT_PHASE_STEP

# How long the hero's vertical bounce keeps animating after reaching its
# final ("Systems online...") state before it settles flat -- every letter
# level -- while the color wash keeps looping. See _HeroArt._settle.
_HERO_SETTLE_SECONDS = 4.0

# Wavy vertical bob applied to the ASCII art: each letter bobs up/down as a
# whole unit, with a phase delay per letter so the bob cascades left-to-right
# (see _HeroArt._wave_offset/_tick). The glyphs in _CLNKR_ART touch with zero
# gap between letters, so per-column ripple sheared individual letters apart;
# bobbing whole letter-column-ranges together keeps each glyph intact.
# Rows of vertical travel. Unipolar (letters only ever lift up from baseline,
# never dip below it -- see _wave_offset) so peak-to-peak travel is a single
# row, not two; that reads as a gentle bounce instead of a big jump.
_WAVE_AMPLITUDE = 1
# Column boundaries between letters in _CLNKR_ART -- "C|L|N|K|R". Tuned to the
# current logo text; update if the ASCII art in app.py changes.
_WAVE_LETTER_BOUNDS = (0, 11, 21, 31, 43, 55)
_WAVE_LETTER_PHASE_SHIFT = 0.9  # radians of phase delay between adjacent letters
_WAVE_PHASE_STEP = 0.6  # radians per tick (time speed)


def _detect_letter_bounds(art_lines: list[str]) -> tuple[int, ...] | None:
    """Detect column boundaries for glyphs separated by blank columns."""
    lines = [line for line in art_lines if line.strip()]
    if len(lines) < 2:
        return None
    width = max(len(line) for line in lines)
    col_has_char = [any(x < len(line) and line[x] != " " for line in lines) for x in range(width)]
    spans: list[tuple[int, int]] = []
    in_letter = False
    start = 0
    for x, has in enumerate(col_has_char):
        if has and not in_letter:
            start = x
            in_letter = True
        elif not has and in_letter:
            spans.append((start, x))
            in_letter = False
    if in_letter:
        spans.append((start, width))
    if len(spans) < 2:
        return None
    return tuple([s for s, _ in spans] + [spans[-1][1]])


class _HeroArt(Static):
    """The animated CLNKR ascii-art hero.

    Repaints itself every animation tick via a bare ``refresh()`` rather than
    ``Static.update()``. The art's line count and width never change between
    frames -- only per-character color and which row of the padded grid gets
    sampled for the bounce -- so the full content-swap ``Static.update()``
    does (which unconditionally requests a relayout, forcing the *whole*
    chat log to re-measure every mounted widget -- see
    ``ChatLog._maybe_prune``) is unneeded tax. A bare repaint only redraws
    this one widget in place, so the cyan-to-blue color gradient wash can keep
    looping for the life of the session at near-zero cost.

    The vertical bounce is a different story: it's a one-time flourish, not
    worth animating forever, so ``settle()`` (fired once, a few seconds
    after the hero reaches its final state) freezes it flat -- every letter
    level -- while the color wash keeps going.
    """

    DEFAULT_CSS = """
    _HeroArt {
        height: auto;
        margin: 0;
        padding: 0;
    }
    """

    _hero_theme: HeroTheme = HeroTheme()

    def __init__(self, hero_theme: HeroTheme | None = None, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._hero_theme: HeroTheme = hero_theme or HeroTheme()
        self._art_lines: list[str] = []
        self._init_text: str = ""
        self._is_final: bool = False
        self._model_info: str = ""
        self._yolo_mode: bool = False
        self._gradient_phase = 0.0
        self._wave_phase = 0.0
        self._wave_settled = True
        self._letter_bounds: tuple[int, ...] = _WAVE_LETTER_BOUNDS
        self._reveal_cols: int | None = None
        self._tick_timer = None
        self._settle_timer = None

    def set_hero_theme(self, hero_theme: HeroTheme) -> None:
        """Update hero banner theme (colors, ASCII art, and animation toggle)."""
        self._hero_theme = hero_theme
        if not self._hero_theme.animation_enabled:
            if self._tick_timer is not None:
                self._tick_timer.stop()
                self._tick_timer = None
        elif self._tick_timer is None and self.is_mounted:
            self._tick_timer = self.set_interval(0.08, self._tick, name="hero-shimmer")
        self.refresh()

    @property
    def _lime_phase(self) -> float:
        return self._gradient_phase

    @_lime_phase.setter
    def _lime_phase(self, val: float) -> None:
        self._gradient_phase = val

    def on_mount(self) -> None:
        if self._hero_theme.animation_enabled:
            self._tick_timer = self.set_interval(0.08, self._tick, name="hero-shimmer")

    def on_unmount(self) -> None:
        if self._tick_timer is not None:
            self._tick_timer.stop()
        if self._settle_timer is not None:
            self._settle_timer.stop()

    def set_art(self, art: str, init_text: str = "", reveal_cols: int | None = None) -> None:
        """Update hero during the boot animation (art reveal + init spinner)."""
        raw_lines = art.split("\n")
        while raw_lines and not raw_lines[0].strip():
            raw_lines.pop(0)
        while raw_lines and not raw_lines[-1].strip():
            raw_lines.pop()
        self._art_lines = raw_lines
        self._init_text = init_text
        self._reveal_cols = reveal_cols
        self._is_final = False
        self.refresh(layout=True)

    def set_final(self, art: str, model_info: str, yolo_mode: bool) -> None:
        """Set the final persistent hero state."""
        raw_lines = art.split("\n")
        while raw_lines and not raw_lines[0].strip():
            raw_lines.pop(0)
        while raw_lines and not raw_lines[-1].strip():
            raw_lines.pop()
        self._art_lines = raw_lines
        self._model_info = model_info
        self._yolo_mode = yolo_mode
        self._reveal_cols = None
        self._is_final = True
        self.refresh(layout=True)

    def _settle(self) -> None:
        """Compatibility method for tests."""
        self._wave_settled = True
        self.refresh()

    def _tick(self) -> None:
        """Advance one animation frame (gradient color wash shimmer)."""
        self._gradient_phase = (self._gradient_phase + _GRADIENT_PHASE_STEP) % 1.0
        self.refresh()

    def _gradient_style(self, x: int, y: int) -> str:
        """RGB style string for gradient wash at grid position (x, y)."""
        phase = self._gradient_phase if self._hero_theme.animation_enabled else 0.0
        wave = (x * _GRADIENT_COL_STEP + y * _GRADIENT_ROW_STEP + phase) % 1.0
        factor = (1 + math.cos(wave * math.tau)) / 2
        r1, g1, b1 = hex_to_rgb(self._hero_theme.gradient_start)
        r2, g2, b2 = hex_to_rgb(self._hero_theme.gradient_end)
        h1, s1, v1 = colorsys.rgb_to_hsv(r1 / 255, g1 / 255, b1 / 255)
        h2, s2, v2 = colorsys.rgb_to_hsv(r2 / 255, g2 / 255, b2 / 255)
        h = h1 + (h2 - h1) * factor
        s = s1 + (s2 - s1) * factor
        v = v1 + (v2 - v1) * factor
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return f"rgb({int(r * 255)},{int(g * 255)},{int(b * 255)})"

    def _lime_shade_style(self, x: int, y: int) -> str:
        return self._gradient_style(x, y)

    def _wave_offset(self, x: int) -> int:
        """Compatibility method returning 0 since vertical wobble is replaced by typewriter slide-in."""
        return 0

    def _append_gradient_art(self, full: Text, art_lines: list[str]) -> None:
        """Append ASCII art lines to *full*, with gradient wash and typewriter column reveal."""
        if not art_lines:
            return

        for y, line in enumerate(art_lines):
            for x, ch in enumerate(line):
                if self._reveal_cols is not None and x >= self._reveal_cols:
                    continue
                if ch.strip():
                    full.append(ch, style=f"bold {self._gradient_style(x, y)}")
                else:
                    full.append(ch)
            if y < len(art_lines) - 1:
                full.append("\n")

    _append_lime_art = _append_gradient_art

    def _build_text(self) -> Text:
        full = Text()

        # ASCII art — cyan-to-blue gradient wash
        self._append_gradient_art(full, self._art_lines)

        full.append("\n")

        if self._is_final:
            online_style = rgb_str(self._hero_theme.system_online_color)
            model_label_style = rgb_str(self._hero_theme.model_label_color)
            model_name_style = rgb_str(self._hero_theme.model_name_color)

            # Systems online
            full.append(
                "  Systems online. Circuits humming. Ready to build.\n", style=f"bold {online_style}"
            )
            full.append("\n")

            # Model line
            full.append("  Model: ", style=model_label_style)
            full.append(self._model_info, style=f"bold {model_name_style}")
            full.append("\n")

            # YOLO indicator
            if self._yolo_mode:
                full.append("\n")
                full.append("  ", style="")
                full.append("YOLO MODE", style="bold yellow")
                full.append(" - bash auto-approved", style=_GREY)
                full.append("\n")

            full.append("\n")

            # Commands hint — grey
            full.append('  Type "/" for commands', style=_GREY)
        elif self._init_text:
            online_style = rgb_str(self._hero_theme.system_online_color)
            # Init / systems online text
            full.append(self._init_text, style=f"bold {online_style}")
            full.append("\n")

        return full

    def render(self) -> Text:
        return self._build_text()


@dataclass
class Message:
    content: str
    type: MessageType = MessageType.ASSISTANT
    title: str = ""
    level: str = "info"
    code_language: str = ""


@dataclass
class ToolEntry:
    """Tracks a tool call's state for animated updates."""
    tool_name: str
    args: str
    status: str  # "running" | "success" | "error"
    result: str = ""
    tool_input: dict = field(default_factory=dict)
    header_widget: Static | None = None
    output_widget: Static | Markdown | None = None
    spinner_timer: object | None = None  # Timer reference for inline spinner


class ChatLog(VerticalScroll):
    """Scrollable chat log displaying conversation messages and tool calls."""

    DEFAULT_CSS = """
    ChatLog {
        width: 100%;
        height: 1fr;
        overflow-y: scroll;
        border: none;
        padding: 0 1 1 1;
    }
    """

    can_focus = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._messages: list[Static | Markdown | Rule] = []
        self._tool_entries: dict[str, ToolEntry] = {}
        self._tool_counter: int = 0

        # Hero state
        self._hero_theme: HeroTheme | None = None
        self._hero_widget: _HeroArt | None = None
        self._hero_rule: Rule | None = None

        # Chat log pruning (bounds live widget count for long sessions)
        self._prune_placeholder: Static | None = None
        self._pruned_count: int = 0

    # --- Hero rendering ---

    @property
    def palette(self) -> ColorPalette:
        return get_theme_config().palette

    def set_hero_theme(self, hero_theme: HeroTheme) -> None:
        """Set the hero banner theme (custom ASCII art, gradient colors, animation)."""
        self._hero_theme = hero_theme
        if self._hero_widget is not None:
            self._hero_widget.set_hero_theme(hero_theme)

    def _ensure_hero_mounted(self) -> _HeroArt:
        if self._hero_widget is None:
            self._hero_widget = _HeroArt(hero_theme=self._hero_theme, id="hero-widget")
            self.mount(self._hero_widget)
            self._messages.append(self._hero_widget)

            self._hero_rule = Rule(line_style="double", classes="hero-divider")
            self._hero_rule.styles.color = rgb_str(self.palette.divider)
            self.mount(self._hero_rule)
            self._messages.append(self._hero_rule)
        return self._hero_widget

    def update_hero_art(self, art: str, init_text: str = "", reveal_cols: int | None = None) -> None:
        """Update hero during animation (typewriter reveal + init spinner)."""
        self._ensure_hero_mounted().set_art(art, init_text, reveal_cols=reveal_cols)

    def update_hero_final(self, art: str, model_info: str, yolo_mode: bool) -> None:
        """Set the final persistent hero state."""
        self._ensure_hero_mounted().set_final(art, model_info, yolo_mode)

    def clear_hero(self) -> None:
        """Remove the hero widget and rule."""
        if self._hero_widget is not None:
            self._hero_widget.remove()
            if self._hero_widget in self._messages:
                self._messages.remove(self._hero_widget)
            self._hero_widget = None

        if self._hero_rule is not None:
            self._hero_rule.remove()
            if self._hero_rule in self._messages:
                self._messages.remove(self._hero_rule)
            self._hero_rule = None

    def add_update_banner(self, current: str, latest: str, install_cmd: str) -> None:
        """Mount a stylized 'update available' card, meant to sit below the hero."""
        badge_style = f"bold black on {rgb_str(self._hero_theme.gradient_start)}"
        arrow_style = f"bold {rgb_str(self._hero_theme.gradient_end)}"
        latest_style = f"bold {rgb_str(self._hero_theme.model_name_color)}"
        cmd_style = f"italic {rgb_str(self._hero_theme.model_label_color)}"
        version_style = f"dim {rgb_str(self._hero_theme.model_label_color)}"

        text = Text()
        text.append(" ⬆  UPDATE AVAILABLE ", style=badge_style)
        text.append("\n\n")
        text.append("  ", style="")
        text.append(f"v{current}", style=version_style)
        text.append("  ─────▶  ", style=arrow_style)
        text.append(f"v{latest}", style=latest_style)
        text.append("\n\n")
        text.append("  ", style="")
        text.append("$ ", style=version_style)
        text.append(install_cmd, style=cmd_style)

        widget = Static(text, classes="update-banner")
        self.mount(widget)
        self._messages.append(widget)
        self._scroll_to_bottom()

    # --- Message rendering ---

    def _create_message_widget(self, msg: Message) -> Static | Markdown:
        handlers = {
            MessageType.USER: self._user_message,
            MessageType.ASSISTANT: self._assistant_message,
            MessageType.NOTIFY: self._notify_message,
            MessageType.SYSTEM: self._system_message,
            MessageType.ERROR: self._error_message,
            MessageType.WARNING: self._warning_message,
            MessageType.INFO: self._info_message,
            MessageType.SUCCESS: self._success_message,
        }
        handler = handlers.get(msg.type)
        if handler:
            return handler(msg)
        return Static(msg.content)

    def _user_message(self, msg: Message) -> Static:
        text = Text()
        text.append("> ", style=f"bold {rgb_str(self.palette.primary)}")
        text.append(msg.content, style=f"bold {rgb_str(self.palette.user_msg)}")
        return Static(text, classes="msg-user")

    def _assistant_message(self, msg: Message) -> Markdown:
        # Mounted empty -- add_message() reveals the content with a
        # typewriter animation via _reveal_markdown() right after mounting.
        md = Markdown("", classes="msg-assistant msg-card")
        md.code_indent_guides = False
        return md

    async def _reveal_markdown(self, widget: Markdown, full_text: str) -> None:
        """Typewriter-reveal an assistant message, chunk by chunk.

        Chunk size scales with message length so the animation always takes
        roughly the same ~0.6s regardless of whether the response is one
        sentence or a long essay, instead of a fixed per-character delay
        that would make long responses crawl.
        """
        length = len(full_text)
        if length == 0:
            return

        target_ticks = 40
        tick_delay = 0.015
        chunk_size = max(1, -(-length // target_ticks))  # ceil(length / target_ticks)

        if not widget.is_attached:
            return
        screen = widget.screen
        selection_guard = (
            screen.suspend_selection()
            if isinstance(screen, SelectionScreen)
            else contextlib.nullcontext()
        )
        with selection_guard:
            revealed = 0
            while revealed < length:
                if not widget.is_attached:
                    return
                revealed = min(length, revealed + chunk_size)
                with contextlib.suppress(Exception):
                    await widget.update(full_text[:revealed])
                self._scroll_to_bottom()
                await asyncio.sleep(tick_delay)

    def _notify_message(self, msg: Message) -> Markdown | Static:
        level_colors = {
            "info": rgb_str(self.palette.notify_info),
            "success": rgb_str(self.palette.notify_success),
            "warning": rgb_str(self.palette.notify_warning),
            "error": rgb_str(self.palette.notify_error),
        }
        color = level_colors.get(msg.level, level_colors["info"])
        content = (msg.content or "").strip()
        if msg.title:
            heading = f"**{msg.title}**\n\n" if content else f"**{msg.title}**"
            content = heading + content
        if not content:
            text = Text("  (no message)", style=f"dim {color}")
            return Static(text, classes="msg-notify msg-card")

        md = Markdown(content, classes=f"msg-notify msg-card notify-{msg.level}")
        md.code_indent_guides = False
        return md

    def _system_message(self, msg: Message) -> Static:
        text = Text(msg.content, style=f"dim {rgb_str(self.palette.system_msg)}")
        return Static(text, classes="msg-system")

    def _error_message(self, msg: Message) -> Static:
        text = Text(f"Error: {msg.content}", style=f"bold {rgb_str(self.palette.notify_error)}")
        return Static(text, classes="msg-error")

    def _warning_message(self, msg: Message) -> Static:
        text = Text(f"Warning: {msg.content}", style=rgb_str(self.palette.notify_warning))
        return Static(text, classes="msg-warning")

    def _info_message(self, msg: Message) -> Static:
        text = Text(msg.content, style=rgb_str(self.palette.notify_info))
        return Static(text, classes="msg-info")

    def _success_message(self, msg: Message) -> Static:
        text = Text(msg.content, style=rgb_str(self.palette.notify_success))
        return Static(text, classes="msg-success")

    # --- Tool rendering ---

    def _tool_badge_text(self, tool_name: str) -> Text:
        display_name = tool_name
        mcp_prefix = ""
        if "__" in tool_name:
            parts = tool_name.split("__", 1)
            mcp_prefix = f"[{parts[0]}] "
            display_name = parts[1]

        text = Text()
        badge_bg = rgb_str(self.palette.tool_card)
        text.append(f" {display_name} ", style=f"bold black on {badge_bg}")
        if mcp_prefix:
            text.append(mcp_prefix, style=f"dim {badge_bg}")
        return text

    def _render_tool_header(self, entry: ToolEntry) -> Text:
        text = Text()
        text.append(self._tool_badge_text(entry.tool_name))

        if entry.args:
            text.append(f" {entry.args}", style=f"dim {rgb_str(self.palette.foreground)}")

        if entry.status == "running":
            frame = getattr(entry, "_spinner_frame", "⠋")
            text.append(f" {frame}", style=f"bold {rgb_str(self.palette.tool_card)}")
        elif entry.status == "success":
            text.append(" ✓", style=f"bold {rgb_str(self.palette.notify_success)}")
        elif entry.status == "error":
            text.append(" ✗", style=f"bold {rgb_str(self.palette.notify_error)}")

        return text

    def _create_output_widget(
        self, result: str, success: bool, tool_name: str, tool_input: dict | None
    ) -> Static | None:
        """Build a one-line result-summary widget below a tool's header.

        Uses the same per-tool summarizer as the CLI (``clanker.ui.tool_summary``)
        instead of a generic JSON/text preview, so e.g. ``load_skill`` shows
        "loaded <name>" rather than a raw JSON dump, and ``execute_shell``
        shows the first output line rather than several raw lines rendered as
        Markdown (which can visually break on stray `#`/`*`/backticks in
        arbitrary command output).

        ``edit_file`` is special-cased to show the actual changed lines (a
        diff) instead of a one-line "patched at line N" summary.
        """
        if tool_name == "edit_file" and success and tool_input:
            old_string = tool_input.get("old_string", "")
            new_string = tool_input.get("new_string", "")
            diff_text = tool_summary.build_edit_diff_text(
                old_string,
                new_string,
                add_color=rgb_str(self.palette.notify_success),
                del_color=rgb_str(self.palette.notify_error),
                hunk_color=f"dim {rgb_str(self.palette.secondary)}",
            )
            if diff_text is not None:
                return Static(diff_text, classes="msg-tool-output tool-card")

        # todo_write/todo_read render as a live pinned panel above the input
        # bar instead (see TodoPanel in app.py) -- the inline transcript just
        # gets the one-line "N/M done" summary like any other tool result.
        summary = tool_summary.compact_result_summary(result, tool_name, tool_input)
        if not summary:
            return None

        color = rgb_str(self.palette.notify_success) if success else rgb_str(self.palette.notify_error)
        text = Text(summary, style=color)
        return Static(text, classes="msg-tool-output tool-card")

    def add_tool_start(
        self, tool_name: str, args: str = "", tool_input: dict | None = None
    ) -> ToolEntry:
        """Add a running tool call with an inline spinner in the header."""
        self.cleanup_pending_thinking()
        self._tool_counter += 1
        key = f"tool:{self._tool_counter}"
        entry = ToolEntry(
            tool_name=tool_name, args=args, status="running", tool_input=tool_input or {}
        )

        header_widget = Static("", classes="msg-tool")
        entry.header_widget = header_widget
        self.mount(header_widget)
        self._messages.append(header_widget)

        # Animate spinner inline in the header
        spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        frame_idx = [0]

        def _tick() -> None:
            if entry.status != "running":
                return
            frame_idx[0] = (frame_idx[0] + 1) % len(spinner_frames)
            entry._spinner_frame = spinner_frames[frame_idx[0]]
            header_widget.update(self._render_tool_header(entry))

        entry._spinner_frame = spinner_frames[0]
        header_widget.update(self._render_tool_header(entry))
        timer = self.set_interval(0.1, _tick, name=f"tool-spinner-{key}")
        entry.spinner_timer = timer

        self._tool_entries[key] = entry
        self._scroll_to_bottom()

        return entry

    def update_tool_progress(self, entry: ToolEntry, current_action: str) -> None:
        """Update a running tool entry's args to show live progress."""
        entry.args = current_action
        if entry.header_widget:
            header = self._render_tool_header(entry)
            entry.header_widget.update(header)
        self._scroll_to_bottom()

    def finalize_subagent(
        self,
        entry: ToolEntry,
        agent_name: str,
        response: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float | None = None,
        success: bool = True,
    ) -> None:
        """Finalize a spawn_subagent tool entry - just show agent badge with status.

        The full response is returned to the parent agent for display via
        normal streaming. Tokens/cost are accumulated in the session tracker
        and shown in the status bar.
        """
        entry.status = "success" if success else "error"
        entry.result = response

        # Stop the spinner timer
        if entry.spinner_timer is not None:
            entry.spinner_timer.pause()
            entry.spinner_timer = None

        # Update header to show agent name as tool badge with status
        header_text = Text()
        subagent_badge_color = rgb_str(self.palette.secondary)
        header_text.append(f" {agent_name} ", style=f"bold black on {subagent_badge_color}")
        if success:
            header_text.append(" ✓", style=f"bold {rgb_str(self.palette.notify_success)}")
        else:
            header_text.append(" ✗", style=f"bold {rgb_str(self.palette.notify_error)}")
        if entry.header_widget:
            entry.header_widget.update(header_text)

        self._scroll_to_bottom()

    def update_tool_end(self, entry: ToolEntry, result: str, success: bool = True) -> None:
        """Update a running tool entry with its result, stopping the spinner."""
        entry.status = "success" if success else "error"
        entry.result = result

        # Stop the spinner timer
        if entry.spinner_timer is not None:
            entry.spinner_timer.pause()
            entry.spinner_timer = None

        if entry.header_widget:
            header = self._render_tool_header(entry)
            entry.header_widget.update(header)

        if result:
            output_widget = self._create_output_widget(
                result, success, entry.tool_name, entry.tool_input
            )
            if output_widget:
                entry.output_widget = output_widget
                self.mount(output_widget, after=entry.header_widget)
                self._messages.append(output_widget)

        self._scroll_to_bottom()

    def add_tool_complete(
        self,
        tool_name: str,
        args: str,
        result: str,
        success: bool = True,
        tool_input: dict | None = None,
    ) -> None:
        """Add a tool that completed instantly (start + end in same tick)."""
        entry = ToolEntry(
            tool_name=tool_name,
            args=args,
            status="success" if success else "error",
            result=result,
            tool_input=tool_input or {},
        )
        header = self._render_tool_header(entry)
        header_widget = Static(header, classes="msg-tool")
        entry.header_widget = header_widget
        self.mount(header_widget)
        self._messages.append(header_widget)

        if result:
            output_widget = self._create_output_widget(result, success, tool_name, entry.tool_input)
            if output_widget:
                entry.output_widget = output_widget
                self.mount(output_widget, after=header_widget)
                self._messages.append(output_widget)

        self._scroll_to_bottom()

    # --- Thinking rendering ---

    # Holds the header widget from add_thinking_start() so that the
    # subsequent add_thinking() can append the body right below it
    # instead of creating a duplicate badge.
    _pending_thinking_header: Static | None = None

    def _thinking_badge_text(self) -> Text:
        text = Text()
        thinking_bg = rgb_str(self.palette.thinking_card)
        text.append(" Thinking ", style=f"bold black on {thinking_bg}")
        return text

    def cleanup_pending_thinking(self) -> None:
        """Remove an orphan pending thinking header if no content was ever emitted."""
        if self._pending_thinking_header is not None:
            with contextlib.suppress(Exception):
                if self._pending_thinking_header in self._messages:
                    self._messages.remove(self._pending_thinking_header)
                self._pending_thinking_header.remove()
            self._pending_thinking_header = None

    def add_thinking_start(self) -> None:
        """Mount the Thinking badge immediately (before content is available).

        Called as soon as the first thinking token arrives so the user sees
        feedback right away.  The body is filled in later by add_thinking().
        """
        if self._pending_thinking_header is not None:
            # Already showing a badge for this thinking block.
            return
        header_widget = Static(self._thinking_badge_text(), classes="msg-tool")
        self.mount(header_widget)
        self._messages.append(header_widget)
        self._pending_thinking_header = header_widget
        self._scroll_to_bottom()

    def add_thinking(self, content: str) -> None:
        """Render a thinking block styled like a tool call: badge header + card body."""
        content = content.strip()
        if not content:
            self.cleanup_pending_thinking()
            return

        display = content[:500] + "..." if len(content) > 500 else content

        if self._pending_thinking_header is not None:
            # Badge was already mounted by add_thinking_start() — reuse it.
            header_widget = self._pending_thinking_header
            self._pending_thinking_header = None
        else:
            header_widget = Static(self._thinking_badge_text(), classes="msg-tool")
            self.mount(header_widget)
            self._messages.append(header_widget)

        body_text = Text(display, style=f"dim italic {rgb_str(self.palette.thinking_card)}")
        body_widget = Static(body_text, classes="msg-tool-output thinking-card")
        self.mount(body_widget, after=header_widget)
        self._messages.append(body_widget)

        self._scroll_to_bottom()

    # --- Public API ---

    def add_message(
        self,
        content: str,
        msg_type: MessageType = MessageType.ASSISTANT,
        title: str = "",
        level: str = "info",
    ) -> None:
        self.cleanup_pending_thinking()
        msg = Message(content=content, type=msg_type, title=title, level=level)
        widget = self._create_message_widget(msg)
        self.mount(widget)
        self._messages.append(widget)
        self._scroll_to_bottom()

        if msg_type == MessageType.ASSISTANT and isinstance(widget, Markdown) and content.strip():
            self.run_worker(self._reveal_markdown(widget, content), exclusive=False)

    def add_code(self, code: str, language: str = "python") -> None:
        syntax = Syntax(code, language, theme="monokai", line_numbers=True)
        widget = Static(syntax, classes="msg-code")
        self.mount(widget)
        self._messages.append(widget)
        self._scroll_to_bottom()

    def add_separator(self) -> None:
        widget = Rule(line_style="dashed", classes="dashed")
        widget.styles.color = rgb_str(self.palette.turn_separator)
        self.mount(widget)
        self._messages.append(widget)
        self._maybe_prune()

    def clear(self) -> None:
        self.cleanup_pending_thinking()
        for msg_widget in self._messages:
            msg_widget.remove()
        self._messages.clear()
        self._tool_entries.clear()
        self._tool_counter = 0
        self._prune_placeholder = None
        self._pruned_count = 0

    def _scroll_to_bottom(self) -> None:
        self.scroll_end(animate=False)
        self._maybe_prune()

    # --- History pruning ---

    def _maybe_prune(self) -> None:
        """Bound the number of live widgets mounted in the chat log.

        Textual re-measures every mounted child of this container whenever
        its layout is invalidated, and normal chat activity (streaming text,
        spinners) invalidates it constantly -- so the cost of routine updates
        scales with total accumulated history, and a long session gradually
        gets slower even when nothing unusual is happening. Once history
        exceeds the configured limit, the oldest entries are unmounted and
        folded into a single placeholder line so the log stays fast without
        silently losing all trace of what happened.
        """
        from clanker.config import get_settings

        limit = max(50, get_settings().output.chat_log_max_widgets)
        overshoot = len(self._messages) - limit
        # Prune in batches (only once meaningfully over the limit, back down
        # to the limit) rather than on every single new widget, so we're not
        # paying a remove-and-relayout on every message once history is long.
        batch_threshold = max(20, limit // 10)
        if overshoot < batch_threshold:
            return

        protected = {self._hero_widget, self._hero_rule, self._prune_placeholder}
        # Never prune a tool call that's still running -- its spinner timer
        # and streaming updates hold a live reference to that widget.
        running_widgets = {
            widget
            for entry in self._tool_entries.values()
            if entry.status == "running"
            for widget in (entry.header_widget, entry.output_widget)
            if widget is not None
        }

        removed: set[object] = set()
        kept: list[Static | Markdown | Rule] = []
        for widget in self._messages:
            if (
                len(removed) < overshoot
                and widget not in protected
                and widget not in running_widgets
            ):
                widget.remove()
                removed.add(widget)
            else:
                kept.append(widget)

        if not removed:
            return

        self._messages = kept
        self._pruned_count += len(removed)

        stale_keys = [
            key for key, entry in self._tool_entries.items() if entry.header_widget in removed
        ]
        for key in stale_keys:
            del self._tool_entries[key]

        self._update_prune_placeholder()

    def _update_prune_placeholder(self) -> None:
        """Show (or update the count on) a single marker for pruned history."""
        text = Text(
            f"⋯ {self._pruned_count} earlier entries hidden to keep this session fast "
            "-- press F3 for full conversation history ⋯",
            style=f"dim {_GREY}",
        )
        if self._prune_placeholder is not None:
            self._prune_placeholder.update(text)
            return

        widget = Static(text, classes="msg-system")
        anchor = self._hero_rule or self._hero_widget
        self.mount(widget, after=anchor)
        self._prune_placeholder = widget

        insert_at = 0
        if anchor is not None and anchor in self._messages:
            insert_at = self._messages.index(anchor) + 1
        self._messages.insert(insert_at, widget)
