"""Status bar widget - shows model info, token usage, and context gauge."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Label

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class StatusBar(Horizontal):
    """Bottom status bar showing model, tokens, and context gauge."""

    can_focus = False

    DEFAULT_CSS = """
    StatusBar {
        width: 100%;
        height: 1;
        dock: top;
        border-top: none;
        padding: 0 1;
        background: black;
        visibility: hidden;
    }

    StatusBar.visible {
        visibility: visible;
    }

    #status-model {
        color: rgb(0,240,240);
        text-style: bold;
    }

    #status-tokens {
        color: rgb(100,100,100);
    }

    #status-context {
        width: 1fr;
        text-align: right;
    }

    #status-subagents {
        color: rgb(0,240,240);
    }
    """

    model_name = reactive("")
    token_info = reactive("")
    context_info = reactive("")
    subagent_info = reactive("")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._subagent_running = 0
        self._subagent_total = 0
        self._spinner_idx = 0

    def on_mount(self) -> None:
        self.set_interval(0.12, self._tick_subagent_spinner)

    def _tick_subagent_spinner(self) -> None:
        if not self._subagent_running:
            return
        self._spinner_idx += 1
        self._render_subagent_info()

    def compose(self) -> ComposeResult:
        yield Label("", id="status-subagents")
        yield Label("", id="status-model")
        yield Label("", id="status-tokens")
        yield Label("", id="status-context")

    def _update_visibility(self) -> None:
        has_content = bool(
            self.model_name or self.token_info or self.context_info or self.subagent_info
        )
        if has_content:
            self.add_class("visible")
        else:
            self.remove_class("visible")

    def watch_model_name(self, value: str) -> None:
        if value:
            self.query_one("#status-model", Label).update(f"  {value}")
        self._update_visibility()

    def watch_token_info(self, value: str) -> None:
        if value:
            self.query_one("#status-tokens", Label).update(f"  {value}")
        else:
            self.query_one("#status-tokens", Label).update("")
        self._update_visibility()

    def watch_context_info(self, value: str) -> None:
        if value:
            self.query_one("#status-context", Label).update(value)
        else:
            self.query_one("#status-context", Label).update("")
        self._update_visibility()

    def watch_subagent_info(self, value: str) -> None:
        self.query_one("#status-subagents", Label).update(f"  {value}" if value else "")
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
            icon = "✓"
        n = self._subagent_total
        self.subagent_info = f"{icon} {n} subagent{'s' if n != 1 else ''} (F2)"

    def set_token_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        context_remaining: float | None = None,
        cost: float | None = None,
    ) -> None:
        parts = [f"in:{input_tokens:,}  out:{output_tokens:,}"]
        if cost is not None:
            parts.append(f"${cost:.4f}")
        self.token_info = "  ".join(parts)

        if context_remaining is not None:
            remaining = max(0.0, context_remaining)
            if remaining > 50:
                style = "rgb(180,255,60)"
            elif remaining > 20:
                style = "rgb(255,220,60)"
            else:
                style = "rgb(255,80,80)"
            bar_width = 16
            filled = int(round(remaining / 100.0 * bar_width))
            filled = max(0, min(bar_width, filled))
            gauge = f"[{style}]{remaining:.0f}% {'█' * filled}{'░' * (bar_width - filled)}[/]"
            self.context_info = gauge
        else:
            self.context_info = ""

    def set_loading(self, message: str = "") -> None:
        self.token_info = f"  {message}"

    def clear(self) -> None:
        self.token_info = ""
        self.context_info = ""
