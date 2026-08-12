"""Popup for viewing the conversation so far.

Renders straight from the app's conversation-message list -- the same list
SessionManager persists to disk (``clanker.memory.checkpointer``) and the
same data ``/restore`` reloads -- rather than anything the chat log has
rendered. That means it stays correct regardless of how much the chat log
has pruned from view (see ``ChatLog._maybe_prune``), and it also works right
after ``/restore``, when the restored turns are never replayed into the chat
log at all.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.rule import Rule
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from clanker.memory.checkpointer import message_content_to_text

_USER_STYLE = "bold rgb(0,240,240)"
_ASSISTANT_STYLE = "bold rgb(180,255,60)"
_RULE_STYLE = "dim rgb(60,60,60)"


class HistoryScreen(ModalScreen[None]):
    """Read-only view of the conversation so far, opened with a hotkey.

    Deliberately simple: one Static holding a single Rich renderable, not a
    widget per turn, so it stays cheap to build even for a long session --
    unlike the live chat log, nothing here needs to stay mounted or animated
    between opens.
    """

    BINDINGS = [
        Binding("escape", "dismiss_screen", "Close", show=True),
        Binding("q", "dismiss_screen", "Close", show=False),
    ]

    DEFAULT_CSS = """
    HistoryScreen {
        align: center middle;
    }

    HistoryScreen > #history-modal {
        width: 90%;
        height: 85%;
        border: round rgb(0,240,240);
        background: black;
    }

    HistoryScreen #history-header {
        padding: 1 2 1 2;
        border-bottom: solid rgb(40,40,40);
    }

    HistoryScreen #history-scroll {
        height: 1fr;
        padding: 1 2;
    }
    """

    def __init__(self, messages: list[BaseMessage]) -> None:
        super().__init__()
        # Kept as the SAME list object the app appends to, not a copy, so
        # a turn that finishes while this is open would still be current if
        # reopened.
        self._messages = messages

    def compose(self) -> ComposeResult:
        with Vertical(id="history-modal"):
            yield Static(self._render_header(), id="history-header")
            with VerticalScroll(id="history-scroll"):
                yield Static(self._render_body(), id="history-body")

    def _turns(self) -> list[BaseMessage]:
        return [
            m
            for m in self._messages
            if isinstance(m, (HumanMessage, AIMessage))
            and message_content_to_text(m.content).strip()
        ]

    def _render_header(self) -> Text:
        count = len(self._turns())
        text = Text()
        text.append("Conversation History", style="bold rgb(0,240,240)")
        text.append(f"   {count} message{'s' if count != 1 else ''}", style="dim")
        return text

    def _render_body(self) -> RenderableType:
        turns = self._turns()
        if not turns:
            return Text(
                "No conversation history yet -- it'll show up here once you "
                "send your first message.",
                style="dim",
            )

        parts: list[RenderableType] = []
        for msg in turns:
            content = message_content_to_text(msg.content)
            if isinstance(msg, HumanMessage):
                if parts:
                    parts.append(Rule(style=_RULE_STYLE))
                parts.append(Text("❯ You", style=_USER_STYLE))
                parts.append(Text(content))
            else:
                parts.append(Text("◆ Clanker", style=_ASSISTANT_STYLE))
                parts.append(Markdown(content))
            parts.append(Text(""))

        return Group(*parts)

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)
