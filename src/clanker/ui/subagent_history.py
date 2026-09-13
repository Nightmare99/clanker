"""Popup for inspecting subagent execution — what ran, what it called, what it returned."""

from __future__ import annotations

import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, ListItem, ListView, Static

from clanker.ui import tool_summary

_STATUS_STYLE = {
    "running": "bold rgb(0,240,240)",
    "success": "bold rgb(180,255,60)",
    "error": "bold rgb(255,105,180)",
}
_STATUS_ICON = {"success": "✓", "error": "✗"}
_STATUS_STYLE.update({"queued": "dim", "waiting": "yellow", "needs_input": "yellow", "stopping": "yellow", "cancelled": "yellow", "timed_out": "yellow", "budget_exceeded": "yellow", "stalled": "yellow"})
_STATUS_ICON.update({"queued": "·", "waiting": "?", "needs_input": "?", "stopping": "◼", "cancelled": "◼", "timed_out": "◷", "budget_exceeded": "!", "stalled": "!"})
_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


@dataclass
class SubagentToolCall:
    """One tool call made by a subagent during its run."""

    tool_name: str
    args: str = ""
    output: str = ""
    status: str = "running"  # running | success
    tool_input: dict = field(default_factory=dict)
    run_id: str = ""


@dataclass
class SubagentRun:
    """Execution record for a single ``spawn_subagent`` invocation."""

    agent_name: str
    prompt: str
    status: str = "running"  # running | success | error
    response: str = ""
    error: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    tool_calls: list[SubagentToolCall] = field(default_factory=list)
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: float = field(default_factory=time.monotonic)
    ended_at: float | None = None
    timeout_seconds: int = 900
    max_tokens: int = 200_000
    model: str | None = None
    working_directory: str = ""
    changed_files: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    pending_messages: int = 0

    @property
    def elapsed_seconds(self) -> float:
        return (self.ended_at or time.monotonic()) - self.started_at


class SubagentHistoryScreen(ModalScreen[None]):
    """Modal listing subagent tasks for the session.

    Opened with a hotkey (F2) so the user can inspect what a subagent did
    without it having flooded the main chat log.
    """

    BINDINGS = [
        Binding("escape", "dismiss_screen", "Close", show=True),
        Binding("q", "dismiss_screen", "Close", show=False),
    ]

    DEFAULT_CSS = """
    SubagentHistoryScreen {
        align: center middle;
    }

    SubagentHistoryScreen > #subagent-modal {
        width: 92%;
        height: 85%;
        border: round rgb(0,240,240);
        background: black;
    }

    SubagentHistoryScreen #subagent-list {
        width: 32%;
        height: 100%;
        border-right: solid rgb(60,60,60);
        padding: 0 1;
    }

    SubagentHistoryScreen #subagent-detail {
        width: 68%;
        height: 100%;
        padding: 1 2;
    }

    SubagentHistoryScreen #subagent-body { height: 1fr; }
    SubagentHistoryScreen #subagent-controls { height: auto; }
    SubagentHistoryScreen #task-message { width: 1fr; }
    SubagentHistoryScreen #task-buttons { height: auto; }
    SubagentHistoryScreen Button { min-width: 8; width: 8; margin-left: 1; }
    SubagentHistoryScreen #task-hint { height: auto; padding: 0 1; }

    SubagentHistoryScreen ListView {
        background: black;
    }

    SubagentHistoryScreen ListItem {
        padding: 0 1;
        background: black;
    }

    SubagentHistoryScreen ListItem.--highlight {
        background: rgb(30,30,30);
    }
    """

    # How often to poll ``self._runs`` for changes while the popup is open.
    # This is plain re-render polling rather than a push/event model because
    # runs are mutated from a subagent's own worker thread (see subagent.py) —
    # polling from the Textual event loop avoids needing thread-safe signaling
    # into a mounted screen for what is a purely cosmetic live view.
    # Fast enough for a smooth spinner animation on running runs/tool calls.
    _POLL_INTERVAL = 0.12

    def __init__(self, runs: list[SubagentRun]) -> None:
        super().__init__()
        # Kept as the SAME list object the app appends new runs to (not a
        # copy) so newly spawned subagents show up while this screen is open.
        self._runs = runs
        self._list_items: list[ListItem] = []
        self._known_len = 0
        self._timer = None
        self._spinner_frame_idx = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="subagent-modal"):
            with VerticalScroll(id="subagent-list"):
                yield ListView(id="subagent-listview")
            with Vertical(id="subagent-detail"):
                with VerticalScroll(id="subagent-body"):
                    yield Static(self._render_detail(0), id="subagent-detail-body")
                yield Static("Enter sends · Stop cancels · Esc closes", id="task-hint")
                with Horizontal(id="subagent-controls"):
                    yield Input(placeholder="Follow-up instruction…", id="task-message")
                    yield Button("Send", id="task-send")
                    yield Button("Stop", id="task-stop", variant="error")

    async def on_mount(self) -> None:
        await self._rebuild_list()
        if self._runs:
            self.query_one("#subagent-listview", ListView).focus()
        self._timer = self.set_interval(self._POLL_INTERVAL, self._refresh_live)

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    async def _rebuild_list(self) -> None:
        """Fully repopulate the list view, preserving the current selection."""
        list_view = self.query_one("#subagent-listview", ListView)
        prev_index = list_view.index
        await list_view.clear()
        self._list_items = []
        self._known_len = len(self._runs)

        if not self._runs:
            await list_view.append(
                ListItem(Static(Text("No subagent tasks yet", style="dim")))
            )
            return

        for i, run in enumerate(self._runs):
            item = ListItem(Static(self._render_list_label(run)), id=f"run-{i}")
            self._list_items.append(item)
            await list_view.append(item)

        list_view.index = prev_index if prev_index is not None and prev_index < len(self._list_items) else 0

    async def _refresh_live(self) -> None:
        """Poll for new runs/tool calls and refresh the visible labels."""
        self._spinner_frame_idx += 1

        if len(self._runs) != self._known_len:
            await self._rebuild_list()

        for item, run in zip(self._list_items, self._runs, strict=False):
            with suppress(Exception):
                item.query_one(Static).update(self._render_list_label(run))

        if not self._runs:
            return
        list_view = self.query_one("#subagent-listview", ListView)
        index = list_view.index if list_view.index is not None else 0
        if 0 <= index < len(self._runs):
            running = self._runs[index].status in ("queued", "running", "waiting")
            self.query_one("#task-stop", Button).disabled = not running
            self.query_one("#task-send", Button).disabled = not running
            with suppress(Exception):
                self.query_one("#subagent-detail-body", Static).update(self._render_detail(index))

    def _status_icon(self, status: str) -> str:
        if status == "running":
            return _SPINNER_FRAMES[self._spinner_frame_idx % len(_SPINNER_FRAMES)]
        return _STATUS_ICON.get(status, "?")

    def _render_list_label(self, run: SubagentRun) -> Text:
        text = Text()
        text.append(f"{self._status_icon(run.status)} ", style=_STATUS_STYLE.get(run.status, "white"))
        text.append(run.agent_name, style="bold white")
        text.append(f"\n{run.status} · {len(run.tool_calls)} calls · {run.elapsed_seconds:.0f}s", style="dim")
        return text

    def _tool_output_summary(self, tc: SubagentToolCall) -> str:
        """Human-readable summary of a tool call's result.

        Reuses the same per-tool summarizer as the main chat log
        (``clanker.ui.tool_summary``) instead of dumping raw JSON/text, so
        e.g. ``read_file`` shows "read 42 lines  foo.py" rather than the
        full raw file content string.
        """
        if not tc.output:
            return ""
        summary = tool_summary.compact_result_summary(
            tc.output, tc.tool_name, tc.tool_input, max_chars=200
        )
        if summary:
            return summary
        raw = tc.output.strip()
        return raw if len(raw) < 300 else raw[:300] + "..."

    def _render_detail(self, index: int) -> Text:
        if not self._runs:
            return Text(
                "Subagent tasks appear here live and remain available throughout this session.",
                style="dim",
            )

        run = self._runs[index]
        text = Text()
        text.append(f"{run.agent_name} · ", style="bold rgb(0,240,240)")
        text.append(f"{run.status}\n\n", style=_STATUS_STYLE.get(run.status, "white"))
        text.append(f"Task {run.task_id} · {run.elapsed_seconds:.0f}s / {run.timeout_seconds}s\n", style="dim")
        text.append(f"Model: {run.model or 'session default'}\n", style="dim")
        text.append(f"Tokens: {run.input_tokens + run.output_tokens:,} / {run.max_tokens:,}\n", style="dim")
        if run.working_directory:
            text.append(f"Workspace: {run.working_directory}\n", style="dim")
        text.append("\n")

        text.append("Prompt\n", style="bold white")
        text.append(f"{run.prompt}\n\n", style="rgb(200,200,200)")
        if run.messages:
            text.append(f"Follow-ups ({run.pending_messages} pending)\n", style="bold white")
            for message in run.messages:
                text.append(f"  {message}\n")
            text.append("\n")
        if run.changed_files:
            text.append("Changed files (file tools)\n", style="bold white")
            text.append("\n".join(run.changed_files) + "\n\n")

        if run.tool_calls:
            text.append("Tool calls\n", style="bold white")
            for tc in run.tool_calls:
                icon = self._status_icon(tc.status)
                style = _STATUS_STYLE.get(tc.status, "white")
                header = f"  {icon} [{tc.tool_name}]"
                if tc.args:
                    header += f" {tc.args}"
                text.append(header + "\n", style=style)
                summary = self._tool_output_summary(tc)
                if summary:
                    text.append(f"      {summary}\n", style="dim")
            text.append("\n")

        if run.response:
            text.append("Response\n", style="bold white")
            text.append(run.response, style="rgb(200,200,200)")
        elif run.error:
            text.append("Error\n", style="bold rgb(255,105,180)")
            text.append(run.error, style="rgb(255,105,180)")

        if run.input_tokens or run.output_tokens:
            tokens_line = f"\n\ntokens: {run.input_tokens:,} in / {run.output_tokens:,} out"
            if run.cost_usd is not None:
                tokens_line += f"  (${run.cost_usd:.4f})"
            text.append(tokens_line, style="dim")

        return text

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is None or not self._runs or not event.item.id:
            return
        try:
            index = int(event.item.id.split("-", 1)[1])
        except (ValueError, IndexError):
            return
        detail = self.query_one("#subagent-detail-body", Static)
        detail.update(self._render_detail(index))

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)

    def _selected_run(self) -> SubagentRun | None:
        index = self.query_one("#subagent-listview", ListView).index
        return self._runs[index] if index is not None and index < len(self._runs) else None

    def _send_message(self) -> None:
        from clanker.tools.subagent import send_task_message

        run = self._selected_run()
        field = self.query_one("#task-message", Input)
        if run and field.value.strip():
            result = send_task_message(run.task_id, field.value.strip())
            self.query_one("#task-hint", Static).update(Text(result))
            if result == "Follow-up queued":
                field.value = ""

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._send_message()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        from clanker.tools.subagent import stop_task

        if event.button.id == "task-send":
            self._send_message()
        elif event.button.id == "task-stop":
            run = self._selected_run()
            if run:
                stop_task(run.task_id)
