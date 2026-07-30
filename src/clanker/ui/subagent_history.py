"""Popup for inspecting subagent execution — what ran, what it called, what it returned."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import ListView, ListItem, Static

from clanker.ui import tool_summary

_STATUS_STYLE = {
    "running": "bold rgb(0,240,240)",
    "success": "bold rgb(180,255,60)",
    "error": "bold rgb(255,80,80)",
}
_STATUS_ICON = {"success": "✓", "error": "✗"}
_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


@dataclass
class SubagentToolCall:
    """One tool call made by a subagent during its run."""

    tool_name: str
    args: str = ""
    output: str = ""
    status: str = "running"  # running | success
    tool_input: dict = field(default_factory=dict)


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


class SubagentHistoryScreen(ModalScreen[None]):
    """Modal listing subagent runs from the current/most recent turn.

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
            with VerticalScroll(id="subagent-detail"):
                yield Static(self._render_detail(0), id="subagent-detail-body")

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
                ListItem(Static(Text("No subagents run yet this turn", style="dim")))
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

        for i, (item, run) in enumerate(zip(self._list_items, self._runs)):
            with suppress(Exception):
                item.query_one(Static).update(self._render_list_label(run))

        if not self._runs:
            return
        list_view = self.query_one("#subagent-listview", ListView)
        index = list_view.index if list_view.index is not None else 0
        if 0 <= index < len(self._runs):
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
        text.append(f"  ({len(run.tool_calls)} calls)", style="dim")
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
                "Nothing to show yet — subagents spawned this turn will appear "
                "here live, and stay until the next message you send.",
                style="dim",
            )

        run = self._runs[index]
        text = Text()
        text.append(f"{run.agent_name}\n", style="bold rgb(0,240,240)")
        text.append(f"{run.status}\n\n", style=_STATUS_STYLE.get(run.status, "white"))

        text.append("Prompt\n", style="bold white")
        text.append(f"{run.prompt}\n\n", style="rgb(200,200,200)")

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
            text.append("Error\n", style="bold rgb(255,80,80)")
            text.append(run.error, style="rgb(255,120,120)")

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
