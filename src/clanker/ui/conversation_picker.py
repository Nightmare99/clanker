"""Paginated conversation picker and guided external-session importer."""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from math import ceil
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, ListItem, ListView, Static

from clanker.memory.importers import SOURCES, ImportCandidate, discover, load

PAGE_SIZE = 10


@dataclass
class ImportSelection:
    candidate: ImportCandidate
    messages: list


class _PagedScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("pageup", "previous_page", "Previous page", priority=True),
        Binding("pagedown", "next_page", "Next page", priority=True),
    ]

    DEFAULT_CSS = """
    _PagedScreen { align: center middle; }
    _PagedScreen > #picker-modal {
        width: 82%; height: 80%;
        border: round rgb(0,240,240); background: black; padding: 1 2;
    }
    _PagedScreen #picker-title { height: 1; color: rgb(0,240,240); text-style: bold; }
    _PagedScreen #picker-help { height: 2; color: rgb(140,140,140); }
    _PagedScreen #picker-search { height: 3; }
    _PagedScreen #picker-list { height: 1fr; background: black; }
    _PagedScreen ListItem { height: 2; padding: 0 1; background: black; }
    _PagedScreen ListItem.--highlight { background: rgb(30,30,30); }
    _PagedScreen #picker-page { height: 1; color: rgb(140,140,140); }
    _PagedScreen #picker-actions { height: 3; margin-top: 1; }
    _PagedScreen Button { margin-right: 1; }
    """

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title
        self._rows: list[tuple[str, str, object]] = []
        self._filtered: list[tuple[str, str, object]] = []
        self._page = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-modal"):
            yield Static(self._title, id="picker-title")
            yield Static("Choose with Enter. Search with Tab. PageUp/PageDown change pages.", id="picker-help")
            yield Input(placeholder="Filter by title, ID, or path", id="picker-search")
            yield ListView(id="picker-list")
            yield Static("", id="picker-page")
            with Horizontal(id="picker-actions"):
                yield Button("Previous", id="picker-prev")
                yield Button("Next page", id="picker-next")
                yield Button("Cancel", id="picker-cancel")

    async def on_mount(self) -> None:
        await self._refresh()
        self.query_one(ListView).focus()

    async def _refresh(self) -> None:
        query = self.query_one("#picker-search", Input).value.casefold().strip()
        self._filtered = [row for row in self._rows if query in (row[0] + " " + row[1]).casefold()]
        pages = max(1, ceil(len(self._filtered) / PAGE_SIZE))
        self._page = min(self._page, pages - 1)
        view = self.query_one(ListView)
        await view.clear()
        start = self._page * PAGE_SIZE
        for label, detail, _ in self._filtered[start:start + PAGE_SIZE]:
            await view.append(ListItem(Static(Text(f"{label}\n{detail}"))))
        if view.children:
            view.index = 0
        self.query_one("#picker-page", Static).update(
            f"{len(self._filtered)} conversations · page {self._page + 1}/{pages}"
        )
        self.query_one("#picker-prev", Button).disabled = self._page == 0
        self.query_one("#picker-next", Button).disabled = self._page >= pages - 1

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "picker-search":
            self._page = 0
            await self._refresh()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "picker-search":
            event.stop()
            self.query_one(ListView).action_select_cursor()

    async def action_previous_page(self) -> None:
        if self._page:
            self._page -= 1
            await self._refresh()

    async def action_next_page(self) -> None:
        if (self._page + 1) * PAGE_SIZE < len(self._filtered):
            self._page += 1
            await self._refresh()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "picker-prev":
            await self.action_previous_page()
        elif event.button.id == "picker-next":
            await self.action_next_page()
        elif event.button.id == "picker-cancel":
            self.action_cancel()

    def _selected(self):
        index = self.query_one(ListView).index
        offset = self._page * PAGE_SIZE + (index if index is not None else -1)
        if 0 <= offset < len(self._filtered):
            return self._filtered[offset][2]
        return None

    def action_cancel(self) -> None:
        # A button event can still arrive after the modal has been dismissed.
        if self.app.screen is self:
            self.dismiss(None)


class ConversationPickerScreen(_PagedScreen):
    """Pick one Clanker session, most recently updated first."""

    def __init__(self, sessions: list[dict]) -> None:
        super().__init__("Resume a conversation")
        sessions = sorted(sessions, key=lambda s: s.get("updated_at") or s.get("created_at") or "", reverse=True)
        self._rows = [
            (str(s.get("title") or "Untitled"),
             f"{s.get('updated_at', '')[:16]}  ·  {s.get('message_count', 0)} messages  ·  {s.get('id', '')}  ·  {s.get('model') or 'model unknown'}",
             s.get("id"))
            for s in sessions
        ]

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        if session_id := self._selected():
            self.dismiss(session_id)


class ImportWizardScreen(_PagedScreen):
    """Choose source, session, then review and import its transcript."""

    BINDINGS = [*_PagedScreen.BINDINGS, Binding("backspace", "back", "Back", priority=False)]

    def __init__(self, working_directory: str | Path | None = None) -> None:
        super().__init__("Import a conversation · 1/3 · Choose source")
        self._working_directory = Path(working_directory or Path.cwd())
        self._stage = "source"
        self._source = ""
        self._candidate: ImportCandidate | None = None
        self._messages: list = []
        self._rows = [(source, "Local conversation history", source) for source in SOURCES]

    async def _refresh(self) -> None:
        await super()._refresh()
        if self._stage == "source":
            self.query_one("#picker-page", Static).update("Choose one of four sources")

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-modal"):
            yield Static(self._title, id="picker-title")
            yield Static("Select a source, choose a conversation, then review it.", id="picker-help")
            yield Input(placeholder="Filter sessions", id="picker-search")
            yield ListView(id="picker-list")
            yield Static("", id="picker-page")
            with Horizontal(id="picker-actions"):
                yield Button("Back", id="wizard-back")
                yield Button("Previous", id="picker-prev")
                yield Button("Next page", id="picker-next")
                yield Button("Import", id="wizard-import", variant="primary")
                yield Button("Cancel", id="picker-cancel")

    async def on_mount(self) -> None:
        await super().on_mount()
        self.query_one("#wizard-import", Button).disabled = True

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        choice = self._selected()
        if choice is None:
            return
        if self._stage == "source":
            self._source = choice
            self.query_one("#picker-title", Static).update(f"Import · 2/3 · {choice} sessions")
            self.query_one("#picker-help", Static).update("Reading local sessions…")
            self._rows = []
            self._stage = "sessions"
            self._page = 0
            self.query_one("#picker-search", Input).value = ""
            await self._refresh()
            try:
                candidates = await asyncio.to_thread(discover, choice, self._working_directory)
            except (OSError, ValueError) as exc:
                self.query_one("#picker-help", Static).update(f"Cannot read sessions: {exc}")
                return
            self._rows = [
                (candidate.title,
                 f"{candidate.updated_at[:16]}  ·  {candidate.session_id}  ·  {candidate.cwd or candidate.path.parent}",
                 candidate)
                for candidate in candidates
            ]
            self.query_one("#picker-help", Static).update(
                "Select a session. Its transcript will be previewed before import."
                if candidates else "No sessions with user prompts found for this workspace. Back chooses another source."
            )
            await self._refresh()
        elif self._stage == "sessions":
            self._candidate = choice
            self.query_one("#picker-help", Static).update("Reading selected transcript…")
            try:
                self._messages = await asyncio.to_thread(load, choice)
            except (OSError, ValueError, sqlite3.Error) as exc:
                self.query_one("#picker-help", Static).update(f"Cannot import this session: {exc}")
                return
            self._stage = "review"
            self.query_one("#picker-title", Static).update("Import · 3/3 · Review")
            self.query_one("#picker-help", Static).update(
                "A new Clanker session will be created with these user and assistant messages."
            )
            first = str(self._messages[0].content).replace("\n", " ")[:90]
            last = str(self._messages[-1].content).replace("\n", " ")[:90]
            self._rows = [
                (choice.title, f"{choice.source}  ·  {len(self._messages)} messages  ·  {choice.cwd or 'workspace unknown'}", None),
                ("First message", first, None), ("Last message", last, None),
            ]
            self.query_one("#picker-search", Input).display = False
            self.query_one("#wizard-import", Button).disabled = False
            await self._refresh()

    async def action_back(self) -> None:
        if self._stage == "source":
            self.action_cancel()
            return
        self._page = 0
        self.query_one("#wizard-import", Button).disabled = True
        self.query_one("#picker-search", Input).display = True
        self.query_one("#picker-search", Input).value = ""
        if self._stage == "review":
            self._stage = "sessions"
            self.query_one("#picker-title", Static).update(f"Import · 2/3 · {self._source} sessions")
            try:
                candidates = await asyncio.to_thread(discover, self._source, self._working_directory)
            except (OSError, ValueError) as exc:
                candidates = []
                self.query_one("#picker-help", Static).update(f"Cannot read sessions: {exc}")
            self._rows = [(c.title, f"{c.updated_at[:16]}  ·  {c.session_id}  ·  {c.cwd or c.path.parent}", c) for c in candidates]
            if candidates:
                self.query_one("#picker-help", Static).update("Select a session.")
        else:
            self._stage = "source"
            self.query_one("#picker-title", Static).update("Import a conversation · 1/3 · Choose source")
            self.query_one("#picker-help", Static).update("Select a source, choose a conversation, then review it.")
            self._rows = [(source, "Local conversation history", source) for source in SOURCES]
        await self._refresh()

    def action_import(self) -> None:
        if self._stage == "review" and self._candidate and self._messages:
            self.dismiss(ImportSelection(self._candidate, self._messages))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "wizard-back":
            event.stop()
            await self.action_back()
        elif event.button.id == "wizard-import":
            event.stop()
            self.action_import()
        else:
            await super().on_button_pressed(event)
