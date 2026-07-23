"""Status bar widget - shows model info, token usage, and context gauge."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Label


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
    """

    model_name = reactive("")
    token_info = reactive("")
    context_info = reactive("")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    def compose(self) -> ComposeResult:
        yield Label("", id="status-model")
        yield Label("", id="status-tokens")
        yield Label("", id="status-context")

    def _update_visibility(self) -> None:
        has_content = bool(self.model_name or self.token_info or self.context_info)
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
