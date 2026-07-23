"""Tool status widget - shows running/completed tool calls."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Literal

from rich.text import Text
from textual.widgets import Static


@dataclass
class ToolCall:
    name: str
    args: str
    status: Literal["running", "success", "error"]
    result: str = ""


_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class ToolStatus(Static):
    """Displays tool call status with badges and animated spinners."""

    DEFAULT_CSS = """
    ToolStatus {
        width: 100%;
        height: auto;
        max-height: 15;
        overflow-y: auto;
        display: none;
    }

    ToolStatus.has-tools {
        display: block;
    }
    """

    BINDINGS = []

    def __init__(self, *args, **kwargs) -> None:
        super().__init__("", *args, **kwargs)
        self._tool_calls: list[ToolCall] = []
        self._pending_tools: dict[str, ToolCall] = {}
        self._tool_counter: int = 0
        self._spinner_iter = itertools.cycle(_SPINNER_FRAMES)

    def add_tool_start(self, tool_name: str, args_str: str = "") -> str:
        """Register a tool that started. Returns tool_id."""
        self._tool_counter += 1
        tool_id = f"{tool_name}:{self._tool_counter}"
        self._pending_tools[tool_id] = ToolCall(
            name=tool_name, args=args_str, status="running"
        )
        self._update_display()
        return tool_id

    def add_tool_end(self, tool_name: str, result: str, success: bool = True) -> None:
        """Mark a tool as completed."""
        for tool_id, tool in list(self._pending_tools.items()):
            if tool.name == tool_name and tool.status == "running":
                tool.status = "success" if success else "error"
                tool.result = result[:80]
                del self._pending_tools[tool_id]
                self._tool_calls.append(tool)
                break
        self._update_display()

    def clear(self) -> None:
        """Clear all tool status."""
        self._tool_calls.clear()
        self._pending_tools.clear()
        self._update_display()

    def has_pending(self) -> bool:
        return bool(self._pending_tools)

    def _format_tool_badge(self, tool_name: str) -> Text:
        """Format tool name as a colored badge."""
        display_name = tool_name
        mcp_prefix = ""
        if "__" in tool_name:
            parts = tool_name.split("__", 1)
            mcp_prefix = f"[{parts[0]}] "
            display_name = parts[1]

        text = Text()
        text.append(f" {display_name} ", style="black on rgb(0,190,220)")
        if mcp_prefix:
            text.append(f" {mcp_prefix}", style="dim cyan")
        return text

    def _update_display(self) -> None:
        """Update the widget display."""
        all_tools = list(self._tool_calls) + list(self._pending_tools.values())
        if not all_tools:
            self.update("")
            self.remove_class("has-tools")
            self._stop_spinner_timer()
            return

        self.add_class("has-tools")
        lines = []
        for tool in all_tools:
            text = Text()
            text.append(self._format_tool_badge(tool.name))
            text.append(" ")

            if tool.args:
                text.append(tool.args, style="rgb(200,220,210)")

            if tool.status == "running":
                frame = next(self._spinner_iter)
                text.append("  ", style="dim")
                text.append(frame, style="dim cyan")
            elif tool.status == "success":
                text.append("  ", style="dim")
                text.append("✓ ", style="bold rgb(130,220,100)")
                if tool.result:
                    text.append(tool.result, style="rgb(130,220,100)")
            elif tool.status == "error":
                text.append("  ", style="dim")
                text.append("✗ ", style="bold red")
                if tool.result:
                    text.append(tool.result, style="bold red")

            lines.append(text)

        self.update("\n".join(str(t) for t in lines))

        # Start/stop spinner timer based on whether tools are running
        if self.has_pending():
            self._start_spinner_timer()
        else:
            self._stop_spinner_timer()

    def _start_spinner_timer(self) -> None:
        """Start periodic spinner animation."""
        self._stop_spinner_timer()
        self.set_interval(0.1, self._update_display, name="tool-spinner")

    def _stop_spinner_timer(self) -> None:
        """Stop periodic spinner animation."""
        try:
            self.remove_interval("tool-spinner")
        except Exception:
            pass
