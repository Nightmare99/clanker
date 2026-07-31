"""Chat log widget - scrollable message history with tool rendering."""

from __future__ import annotations

import asyncio
import colorsys
import contextlib
from dataclasses import dataclass, field
from enum import StrEnum

from rich import box
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Markdown, Rule, Static

from clanker.ui import tool_summary


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
_GREEN = "rgb(180,255,60)"
_LIME = "rgb(180,255,60)"
_WHITE = "white"
_GREY = "rgb(100,100,100)"

# Rainbow wash over the ASCII art: how fast the hue shifts across columns/rows,
# and how far the phase advances per tick (see _rainbow_style/_rainbow_tick).
_RAINBOW_COL_STEP = 0.02
_RAINBOW_ROW_STEP = 0.06
_RAINBOW_PHASE_STEP = 0.02


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
        border: round rgb(0,240,240);
        padding: 1;
    }
    """

    can_focus = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._messages: list[Static | Markdown | Rule] = []
        self._tool_entries: dict[str, ToolEntry] = {}
        self._tool_counter: int = 0

        # Hero state
        self._hero_widget: Static | None = None
        self._hero_rule: Rule | None = None
        self._hero_art_lines: list[str] = []
        self._hero_init_text: str = ""
        self._hero_final_model: str = ""
        self._hero_final_yolo: bool = False
        self._hero_is_final: bool = False
        self._rainbow_timer = None
        self._rainbow_phase = 0.0

    def on_mount(self) -> None:
        self._rainbow_timer = self.set_interval(0.08, self._rainbow_tick, name="hero-rainbow")

    # --- Hero rendering ---

    def _rainbow_style(self, x: int, y: int) -> str:
        """RGB style string for a lolcat-style rainbow wash at grid position (x, y)."""
        hue = (x * _RAINBOW_COL_STEP + y * _RAINBOW_ROW_STEP + self._rainbow_phase) % 1.0
        r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 1.0)
        return f"rgb({int(r * 255)},{int(g * 255)},{int(b * 255)})"

    def _append_rainbow_art(self, full: Text, art_lines: list[str]) -> None:
        """Append ASCII art lines to *full*, coloring each glyph with the rainbow wash."""
        for y, line in enumerate(art_lines):
            for x, ch in enumerate(line):
                if ch.strip():
                    full.append(ch, style=f"bold {self._rainbow_style(x, y)}")
                else:
                    full.append(ch)
            if y < len(art_lines) - 1:
                full.append("\n")

    def _build_hero_text(self, art: str, init_text: str = "") -> Text:
        """Build a Rich Text for the hero with per-section colors."""
        full = Text()

        # ASCII art — rainbow wash
        self._append_rainbow_art(full, art.split("\n"))

        full.append("\n")

        # Init / systems online text — green
        if init_text:
            full.append(init_text, style=f"bold {_GREEN}")
            full.append("\n")

        return full

    def _build_hero_final(self, art: str, model_info: str, yolo_mode: bool) -> Text:
        """Build the final persistent hero with colored sections."""
        full = Text()

        # ASCII art — rainbow wash
        self._append_rainbow_art(full, art.split("\n"))

        full.append("\n")

        # Systems online — green
        full.append("  Systems online. Circuits humming. Ready to build.\n", style=f"bold {_GREEN}")
        full.append("\n")

        # Model line — label white, name lime
        full.append("  Model: ", style=_WHITE)
        full.append(model_info, style=f"bold {_LIME}")
        full.append("\n")

        # YOLO indicator
        if yolo_mode:
            full.append("\n")
            full.append("  ", style="")
            full.append("YOLO MODE", style="bold yellow")
            full.append(" - bash auto-approved", style=_GREY)
            full.append("\n")

        full.append("\n")

        # Commands hint — grey
        full.append('  Type "/" for commands', style=_GREY)

        return full

    def _rainbow_tick(self) -> None:
        """Advance the rainbow phase and re-render the hero's ASCII art."""
        if self._hero_widget is None:
            return
        self._rainbow_phase = (self._rainbow_phase + _RAINBOW_PHASE_STEP) % 1.0
        if self._hero_is_final:
            self._hero_widget.update(self._build_hero_final(
                "\n".join(self._hero_art_lines),
                self._hero_final_model,
                self._hero_final_yolo,
            ))
        else:
            self._hero_widget.update(self._build_hero_text(
                "\n".join(self._hero_art_lines), self._hero_init_text
            ))

    def update_hero_art(self, art: str, init_text: str = "") -> None:
        """Update hero during animation (art reveal + init spinner)."""
        self._hero_art_lines = art.split("\n")
        self._hero_init_text = init_text
        self._hero_is_final = False

        if self._hero_widget is None:
            self._hero_widget = Static("", id="hero-widget")
            self.mount(self._hero_widget)
            self._messages.append(self._hero_widget)

            self._hero_rule = Rule(line_style="double")
            self.mount(self._hero_rule)
            self._messages.append(self._hero_rule)

        self._hero_widget.update(self._build_hero_text(art, init_text))

    def update_hero_final(self, art: str, model_info: str, yolo_mode: bool) -> None:
        """Set the final persistent hero state."""
        self._hero_art_lines = art.split("\n")
        self._hero_final_model = model_info
        self._hero_final_yolo = yolo_mode
        self._hero_is_final = True
        self._hero_init_text = ""

        if self._hero_widget is None:
            self._hero_widget = Static("", id="hero-widget")
            self.mount(self._hero_widget)
            self._messages.append(self._hero_widget)

            self._hero_rule = Rule(line_style="double")
            self.mount(self._hero_rule)
            self._messages.append(self._hero_rule)

        self._hero_widget.update(self._build_hero_final(art, model_info, yolo_mode))

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

        self._hero_art_lines = []
        self._hero_init_text = ""
        self._hero_is_final = False

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
        text.append("> ", style="bold rgb(0,240,240)")
        text.append(msg.content, style="bold white")
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

        revealed = 0
        while revealed < length:
            revealed = min(length, revealed + chunk_size)
            with contextlib.suppress(Exception):
                await widget.update(full_text[:revealed])
            self._scroll_to_bottom()
            await asyncio.sleep(tick_delay)

    def _notify_message(self, msg: Message) -> Markdown | Static:
        level_colors = {
            "info": "rgb(0,240,240)",
            "success": "rgb(180,255,60)",
            "warning": "rgb(255,220,60)",
            "error": "rgb(255,80,80)",
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
        text = Text(msg.content, style="dim rgb(0,240,240)")
        return Static(text, classes="msg-system")

    def _error_message(self, msg: Message) -> Static:
        text = Text(f"Error: {msg.content}", style="bold rgb(255,80,80)")
        return Static(text, classes="msg-error")

    def _warning_message(self, msg: Message) -> Static:
        text = Text(f"Warning: {msg.content}", style="rgb(255,220,60)")
        return Static(text, classes="msg-warning")

    def _info_message(self, msg: Message) -> Static:
        text = Text(msg.content, style="rgb(0,240,240)")
        return Static(text, classes="msg-info")

    def _success_message(self, msg: Message) -> Static:
        text = Text(msg.content, style="rgb(180,255,60)")
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
        text.append(f" {display_name} ", style="black on rgb(0,240,240)")
        if mcp_prefix:
            text.append(mcp_prefix, style="dim rgb(0,240,240)")
        return text

    def _render_tool_header(self, entry: ToolEntry) -> Text:
        text = Text()
        text.append(self._tool_badge_text(entry.tool_name))

        if entry.args:
            text.append(f" {entry.args}", style="rgb(180,200,190)")

        if entry.status == "running":
            frame = getattr(entry, "_spinner_frame", "⠋")
            text.append(f" {frame}", style="bold rgb(0,240,240)")
        elif entry.status == "success":
            text.append(" ✓", style="bold rgb(180,255,60)")
        elif entry.status == "error":
            text.append(" ✗", style="bold rgb(255,80,80)")

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
            diff_text = tool_summary.build_edit_diff_text(old_string, new_string)
            if diff_text is not None:
                return Static(diff_text, classes="msg-tool-output tool-card")

        summary = tool_summary.compact_result_summary(result, tool_name, tool_input)
        if not summary:
            return None

        color = "rgb(130,220,100)" if success else "rgb(255,80,80)"
        text = Text(summary, style=color)
        return Static(text, classes="msg-tool-output tool-card")

    def add_tool_start(
        self, tool_name: str, args: str = "", tool_input: dict | None = None
    ) -> ToolEntry:
        """Add a running tool call with an inline spinner in the header."""
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
        header_text.append(f" {agent_name} ", style="black on rgb(0,240,240)")
        if success:
            header_text.append(" ✓", style="bold rgb(180,255,60)")
        else:
            header_text.append(" ✗", style="bold rgb(255,80,80)")
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

    def _thinking_badge_text(self) -> Text:
        text = Text()
        text.append(" Thinking ", style="black on rgb(180,140,255)")
        return text

    def add_thinking(self, content: str) -> None:
        """Render a thinking block styled like a tool call: badge header + card body."""
        content = content.strip()
        if not content:
            return

        display = content[:500] + "..." if len(content) > 500 else content

        header_widget = Static(self._thinking_badge_text(), classes="msg-tool")
        self.mount(header_widget)
        self._messages.append(header_widget)

        body_text = Text(display, style="dim italic rgb(190,180,220)")
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
        widget = Rule(line_style="dashed")
        self.mount(widget)
        self._messages.append(widget)

    def clear(self) -> None:
        for msg_widget in self._messages:
            msg_widget.remove()
        self._messages.clear()
        self._tool_entries.clear()
        self._tool_counter = 0

    def _scroll_to_bottom(self) -> None:
        self.scroll_end(animate=False)
