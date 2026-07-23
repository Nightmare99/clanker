"""Chat log widget - scrollable message history with tool rendering."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from rich import box
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Markdown, Rule, Static


class MessageType(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    THINKING = "thinking"
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
_BLINK_CHARS = ("█", " ")


@dataclass
class Message:
    content: str
    type: MessageType = MessageType.ASSISTANT
    title: str = ""
    code_language: str = ""


@dataclass
class ToolEntry:
    """Tracks a tool call's state for animated updates."""
    tool_name: str
    args: str
    status: str  # "running" | "success" | "error"
    result: str = ""
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
        self._blink_timer = None
        self._blink_state = 0  # 0 = visible, 1 = hidden
        self._blink_running = False

    def on_mount(self) -> None:
        self._blink_timer = self.set_interval(
            0.5, self._blink_tick, name="hero-blink", repeat=0, pause=True
        )

    # --- Hero rendering ---

    def _build_hero_text(self, art: str, init_text: str = "") -> Text:
        """Build a Rich Text for the hero with per-section colors."""
        full = Text()

        # ASCII art — cyan
        art_lines = art.split("\n")
        for i, line in enumerate(art_lines):
            full.append(line, style=f"bold {_CYAN}")
            if i < len(art_lines) - 1:
                full.append("\n")

        full.append("\n")

        # Init / systems online text — green
        if init_text:
            full.append(init_text, style=f"bold {_GREEN}")
            full.append("\n")

        return full

    def _build_hero_final(self, art: str, model_info: str, yolo_mode: bool) -> Text:
        """Build the final persistent hero with colored sections."""
        full = Text()

        # ASCII art — cyan with blinking cursor on last non-empty line
        art_lines = art.split("\n")
        cursor_char = _BLINK_CHARS[self._blink_state]

        # Find the last non-empty line to place the cursor next to
        last_content_idx = -1
        for i in range(len(art_lines) - 1, -1, -1):
            if art_lines[i].strip():
                last_content_idx = i
                break

        for i, line in enumerate(art_lines):
            full.append(line, style=f"bold {_CYAN}")
            if i == last_content_idx:
                full.append(f" {cursor_char * 8}", style=f"bold {_LIME}")
            if i < len(art_lines) - 1:
                full.append("\n")

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

    def _blink_tick(self) -> None:
        """Toggle the blinking cursor in the hero."""
        if self._hero_widget is None:
            return
        self._blink_state = 1 - self._blink_state
        if self._hero_is_final:
            self._hero_widget.update(self._build_hero_final(
                "\n".join(self._hero_art_lines),
                self._hero_final_model,
                self._hero_final_yolo,
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

        if self._blink_timer and not self._blink_running:
            self._blink_running = True
            self._blink_timer.resume()

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

        if self._blink_timer:
            self._blink_running = False
            self._blink_timer.pause()

        self._hero_art_lines = []
        self._hero_init_text = ""
        self._hero_is_final = False

    # --- Message rendering ---

    def _create_message_widget(self, msg: Message) -> Static | Markdown:
        handlers = {
            MessageType.USER: self._user_message,
            MessageType.ASSISTANT: self._assistant_message,
            MessageType.THINKING: self._thinking_message,
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
        md = Markdown(msg.content, classes="msg-assistant msg-card")
        md.code_indent_guides = False
        return md

    def _thinking_message(self, msg: Message) -> Static:
        display = msg.content[:500] + "..." if len(msg.content) > 500 else msg.content
        text = Text()
        text.append("  ", style="dim")
        text.append(display, style="dim italic rgb(100,100,100)")
        return Static(text, classes="msg-thinking")

    def _notify_message(self, msg: Message) -> Markdown | Static:
        level_colors = {
            "info": "rgb(0,240,240)",
            "success": "rgb(180,255,60)",
            "warning": "rgb(255,220,60)",
            "error": "rgb(255,80,80)",
        }
        color = level_colors.get(msg.title, level_colors["info"])
        content = (msg.content or "").strip()
        if not content:
            text = Text("  (no message)", style=f"dim {color}")
            return Static(text, classes="msg-notify msg-card")

        md = Markdown(content, classes=f"msg-notify msg-card notify-{msg.title}")
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

    def _format_tool_output(self, result: str, max_lines: int = 3) -> str:
        result = (result or "").strip()
        if not result:
            return ""

        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                if parsed.get("ok"):
                    if "message" in parsed:
                        return str(parsed["message"])[:300]
                    if "content" in parsed:
                        content = str(parsed["content"])
                        lines = content.split("\n")
                        snippet = "\n".join(lines[:max_lines])
                        if len(lines) > max_lines:
                            snippet += f"\n... (+{len(lines) - max_lines} more)"
                        return snippet[:300]
                    if "path" in parsed:
                        lines_count = parsed.get("lines", "")
                        path = str(parsed["path"])
                        if lines_count:
                            return f"{path}  ({lines_count} lines)"
                        return path
                if not parsed.get("ok", True) and "error" in parsed:
                    return str(parsed["error"])[:300]
        except (json.JSONDecodeError, ValueError):
            pass

        if result.startswith("Command exited with code"):
            lines = result.split("\n")
            first = lines[0]
            rest = "\n".join(lines[1:max_lines + 1])
            if len(lines) > max_lines + 1:
                rest += f"\n... (+{len(lines) - max_lines - 1} more)"
            return f"{first}\n{rest}"[:300] if rest else first

        lines = result.split("\n")
        snippet = "\n".join(lines[:max_lines])
        if len(lines) > max_lines:
            snippet += f"\n... (+{len(lines) - max_lines} more)"
        return snippet[:300]

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

    def _create_output_widget(self, result: str, success: bool) -> Markdown | None:
        preview = self._format_tool_output(result)
        if not preview:
            return None

        md = Markdown(preview, classes="msg-tool-output tool-card")
        return md

    def add_tool_start(self, tool_name: str, args: str = "") -> ToolEntry:
        """Add a running tool call with an inline spinner in the header."""
        self._tool_counter += 1
        key = f"tool:{self._tool_counter}"
        entry = ToolEntry(tool_name=tool_name, args=args, status="running")

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
            output_widget = self._create_output_widget(result, success)
            if output_widget:
                entry.output_widget = output_widget
                self.mount(output_widget)
                self._messages.append(output_widget)

        self._scroll_to_bottom()

    def add_tool_complete(
        self, tool_name: str, args: str, result: str, success: bool = True
    ) -> None:
        """Add a tool that completed instantly (start + end in same tick)."""
        entry = ToolEntry(
            tool_name=tool_name,
            args=args,
            status="success" if success else "error",
            result=result,
        )
        header = self._render_tool_header(entry)
        header_widget = Static(header, classes="msg-tool")
        entry.header_widget = header_widget
        self.mount(header_widget)
        self._messages.append(header_widget)

        if result:
            output_widget = self._create_output_widget(result, success)
            if output_widget:
                entry.output_widget = output_widget
                self.mount(output_widget)
                self._messages.append(output_widget)

        self._scroll_to_bottom()

    # --- Public API ---

    def add_message(
        self,
        content: str,
        msg_type: MessageType = MessageType.ASSISTANT,
        title: str = "",
    ) -> None:
        msg = Message(content=content, type=msg_type, title=title)
        widget = self._create_message_widget(msg)
        self.mount(widget)
        self._messages.append(widget)
        self._scroll_to_bottom()

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
