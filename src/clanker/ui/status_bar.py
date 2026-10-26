"""Top session status and bottom context/loading status widgets."""

from __future__ import annotations

from contextlib import suppress

from textual import _border
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Label

from clanker.config.theme import get_theme_config, rgb_str

# Use thin hairline overline (U+203E) for tab bottom border instead of thick 1/8 block
_border.BORDER_CHARS["tab"] = (
    ("▁", "▁", "▁"),
    ("▎", " ", "▊"),
    ("‾", "‾", "‾"),
)

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class StatusBar(Horizontal):
    """Top status bar showing the session, usage, and selected model."""

    can_focus = False

    DEFAULT_CSS = """
    StatusBar {
        width: 100%;
        height: auto;
        dock: top;
        border: none;
        border-bottom: tab rgb(60,60,80);
        margin: 0;
        padding: 0 1;
        background: black;
        visibility: hidden;
    }

    StatusBar.visible {
        visibility: visible;
    }

    #status-subagents {
        color: rgb(0,240,240);
        width: 1fr;
        height: 1;
        text-align: left;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }

    #status-tokens {
        color: rgb(100,100,100);
        width: auto;
        height: 1;
        text-align: center;
        text-wrap: nowrap;
    }

    #status-model {
        color: rgb(0,240,240);
        text-style: bold;
        width: 1fr;
        height: 1;
        text-wrap: nowrap;
        text-overflow: ellipsis;
        text-align: right;
    }
    """

    session_id = reactive("")
    model_name = reactive("")
    token_info = reactive("")
    context_info = reactive("")
    loading_info = reactive("")
    subagent_info = reactive("")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._subagent_running = 0
        self._subagent_total = 0
        self._spinner_idx = 0
        self._compacting = False
        self._compact_frame = 0
        self._last_context_remaining: float | None = None

    def on_mount(self) -> None:
        self.set_interval(0.12, self._tick_spinner)

    def _tick_spinner(self) -> None:
        if self._compacting:
            self._compact_frame += 1
            bar_width = 16
            frame = self._compact_frame % bar_width
            cells = ["░"] * bar_width
            cells[frame] = "█"
            cells[(frame + 1) % bar_width] = "█"
            compact_color = rgb_str(get_theme_config().palette.bottom_bar_context)
            self.context_info = f"[{compact_color}]compacting {''.join(cells)}[/]"
        if not self._subagent_running:
            return
        self._spinner_idx += 1
        self._render_subagent_info()

    def compose(self) -> ComposeResult:
        yield Label("", id="status-subagents")
        yield Label("", id="status-tokens")
        yield Label("", id="status-model", markup=False)

    def _update_visibility(self) -> None:
        has_content = bool(
            self.model_name or self.token_info or self.subagent_info
        )
        if has_content:
            self.add_class("visible")
        else:
            self.remove_class("visible")

    def watch_model_name(self, value: str) -> None:
        with suppress(Exception):
            self.query_one("#status-model", Label).update(value or "")
        self._update_visibility()

    def watch_session_id(self, value: str) -> None:
        pass

    def watch_token_info(self, value: str) -> None:
        with suppress(Exception):
            self.query_one("#status-tokens", Label).update(value or "")
        self._update_visibility()

    def watch_subagent_info(self, value: str) -> None:
        with suppress(Exception):
            self.query_one("#status-subagents", Label).update(value or "")
        self._update_visibility()

    def set_subagent_runs(self, running: int, total: int) -> None:
        """Show a hint that subagents are running/have run, with the hotkey to inspect."""
        self._subagent_running = running
        self._subagent_total = total
        self._render_subagent_info()

    def _render_subagent_info(self) -> None:
        if self._subagent_total == 0:
            self.subagent_info = ""
            return
        if self._subagent_running:
            icon = _SPINNER_FRAMES[self._spinner_idx % len(_SPINNER_FRAMES)]
        else:
            icon = "⚡"
        n = self._subagent_total
        self.subagent_info = f"{icon} {n} subagent{'s' if n != 1 else ''} (F2)"

    def set_token_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        context_remaining: float | None = None,
        cost: float | None = None,
        subagent_input_tokens: int = 0,
        subagent_output_tokens: int = 0,
        subagent_cost: float | None = None,
    ) -> None:
        if subagent_input_tokens > 0 or subagent_output_tokens > 0:
            parts = [
                f"main: in:{input_tokens:,} out:{output_tokens:,}",
                f"subagents: in:{subagent_input_tokens:,} out:{subagent_output_tokens:,}",
            ]
        else:
            parts = [f"in:{input_tokens:,}  out:{output_tokens:,}"]
        total_cost = None
        if cost is not None or subagent_cost is not None:
            total_cost = (cost or 0.0) + (subagent_cost or 0.0)
        if total_cost is not None:
            parts.append(f"${total_cost:.4f}")
        self.token_info = "  ".join(parts)
        self.update_context_remaining(context_remaining)

    def set_compacting(self, compacting: bool = True) -> None:
        """Toggle the compacting animation on the context gauge."""
        self._compacting = compacting
        if compacting:
            self._compact_frame = 0
            compact_color = rgb_str(get_theme_config().palette.bottom_bar_context)
            self.context_info = f"[{compact_color}]compacting ░░░░░░░░░░░░░░░░[/]"
        elif self._last_context_remaining is not None:
            self.update_context_remaining(self._last_context_remaining)
        else:
            self.context_info = ""

    def update_context_remaining(self, remaining: float | None) -> None:
        """Update the fuel gauge with the percentage of context remaining."""
        self._last_context_remaining = remaining
        if self._compacting:
            return
        if remaining is not None:
            pal = get_theme_config().palette
            rem = max(0.0, remaining)
            if rem > 50:
                style = rgb_str(pal.notify_success)
            elif rem > 20:
                style = rgb_str(pal.notify_warning)
            else:
                style = rgb_str(pal.notify_error)
            bar_width = 16
            filled = int(round(rem / 100.0 * bar_width))
            filled = max(0, min(bar_width, filled))
            unfilled_color = rgb_str(pal.status_bar_tokens)
            gauge = f"[{style}]{rem:.0f}% {'█' * filled}[/][{unfilled_color}]{'░' * (bar_width - filled)}[/]"
            self.context_info = gauge
        else:
            self.context_info = ""

    def set_loading(self, message: str = "") -> None:
        self.loading_info = message

    def clear(self) -> None:
        """Stop the loading hint while retaining the last usage snapshot."""
        self.loading_info = ""


class WorkspaceStatus(Horizontal):
    """One bottom line for session/help/loading on the left and context on the right."""

    DEFAULT_CSS = """
    WorkspaceStatus {
        height: 1;
        padding: 0 1;
        color: rgb(140,140,140);
    }
    WorkspaceStatus #status-session {
        color: rgb(180,255,60);
        text-style: bold;
        width: auto;
        margin-right: 2;
    }
    WorkspaceStatus #workspace-hint {
        width: 1fr;
        height: 1;
        text-wrap: nowrap;
        text-overflow: ellipsis;
        text-align: right;
    }
    WorkspaceStatus #status-context {
        width: auto;
        height: 1;
        margin-left: 2;
        text-wrap: nowrap;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("", id="status-session", markup=False)
        yield Label("F1 Help · F3 History · /reload to refresh", id="workspace-hint", markup=False)
        yield Label("", id="status-context")

    def set_session_id(self, session_id: str) -> None:
        with suppress(Exception):
            label = self.query_one("#status-session", Label)
            if session_id:
                label.update(f"Session ID: {session_id}")
                label.display = True
            else:
                label.update("")
                label.display = False

    def set_loading(self, message: str) -> None:
        with suppress(Exception):
            self.query_one("#workspace-hint", Label).update(
                message or "F1 Help · F3 History · /reload to refresh"
            )

    def set_context(self, context: str) -> None:
        with suppress(Exception):
            self.query_one("#status-context", Label).update(context)
