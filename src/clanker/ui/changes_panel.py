"""Keyboard-accessible session diffs and conflict-aware undo."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, ListItem, ListView, Static

from clanker.changes import Change, ChangeJournal


class ChangesScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("u", "undo_edit", "Undo edit"),
        Binding("t", "undo_turn", "Undo turn"),
    ]
    DEFAULT_CSS = """
    ChangesScreen { align: center middle; }
    ChangesScreen #changes-modal {
        width: 94%; height: 90%; border: round rgb(0,240,240); background: black;
    }
    ChangesScreen #changes-header { height: auto; padding: 1; }
    ChangesScreen #changes-columns { height: 1fr; }
    ChangesScreen #changes-list { width: 35%; border-right: solid rgb(60,60,60); }
    ChangesScreen #changes-detail { width: 65%; padding: 0 1; }
    ChangesScreen #changes-actions { height: auto; padding: 0 1; }
    ChangesScreen #changes-notice { height: auto; padding: 0 1; }
    ChangesScreen Button { margin-right: 1; }
    """

    def __init__(
        self,
        journal: ChangeJournal,
        working_directory: str,
        is_busy: Callable[[], bool] = lambda: False,
        on_undo: Callable[[tuple[int, ...]], None] | None = None,
    ) -> None:
        super().__init__()
        self.journal = journal
        self.root = Path(working_directory)
        self.is_busy = is_busy
        self.on_undo = on_undo
        self._changes: list[Change] = []
        self._revision = -1
        self._confirm: tuple[int, ...] = ()
        self._undoing = False

    def compose(self) -> ComposeResult:
        with Vertical(id="changes-modal"):
            yield Static(
                "Changes · this session\nFile-tool edits only; shell and MCP edits are not tracked.",
                id="changes-header",
            )
            with Horizontal(id="changes-columns"):
                yield ListView(id="changes-list")
                with VerticalScroll(id="changes-detail"):
                    yield Static("No recorded edits yet.", id="changes-diff")
            yield Static("Select an edit to review. Esc closes this panel.", id="changes-notice")
            with Horizontal(id="changes-actions"):
                yield Button("Undo edit (u)", id="undo-edit")
                yield Button("Undo turn (t)", id="undo-turn")
                yield Button("Close (Esc)", id="close-changes")

    async def on_mount(self) -> None:
        await self._refresh_changes()
        self.query_one(ListView).focus()
        self.set_interval(0.5, self._refresh_changes)

    async def _refresh_changes(self) -> None:
        busy = self.is_busy() or self._undoing
        self.query_one("#undo-edit", Button).disabled = busy
        self.query_one("#undo-turn", Button).disabled = busy
        if self._revision == self.journal.revision:
            return
        self._revision = self.journal.revision
        selected = self._selected()
        self._changes = list(reversed(self.journal.snapshot()))
        view = self.query_one(ListView)
        index = next(
            (i for i, change in enumerate(self._changes) if selected and change.id == selected.id),
            0,
        )
        await view.clear()
        for change in self._changes:
            try:
                name = str(change.path.relative_to(self.root))
            except ValueError:
                name = str(change.path)
            state = "undone" if change.undone else ("new" if change.before is None else "edit")
            await view.append(
                ListItem(Static(Text(f"{name}\n{state} · turn {change.turn} · {change.actor}")))
            )
        if self._changes:
            view.index = min(index, len(self._changes) - 1)
            self._show_diff()

    def _selected(self) -> Change | None:
        index = self.query_one(ListView).index
        return self._changes[index] if index is not None and index < len(self._changes) else None

    def _show_diff(self) -> None:
        change = self._selected()
        if change:
            diff = change.diff()
            # Keep huge writes reviewable without mounting megabytes of text.
            if len(diff) > 100_000:
                diff = (
                    diff[:100_000] + "\n… preview truncated; inspect the file for the full content."
                )
            self.query_one("#changes-diff", Static).update(
                Syntax(diff or "(No textual difference)", "diff", word_wrap=True)
            )

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        self._confirm = ()
        self._show_diff()

    async def _undo(self, whole_turn: bool) -> None:
        if self.is_busy() or self._undoing:
            self.query_one("#changes-notice", Static).update(
                "Stop running agents before undoing changes."
            )
            return
        change = self._selected()
        if change is None or change.undone:
            return
        ids = tuple(
            c.id
            for c in self.journal.snapshot()
            if not c.undone and (c.turn == change.turn if whole_turn else c.id == change.id)
        )
        notice = self.query_one("#changes-notice", Static)
        if self._confirm != ids:
            self._confirm = ids
            notice.update(f"Undo {len(ids)} edit(s)? Press the same undo control again to confirm.")
            return
        self._undoing = True
        try:
            count = await asyncio.to_thread(self.journal.undo, list(ids))
            notice.update(f"Undid {count} edit(s).")
            if self.on_undo:
                self.on_undo(ids)
        except (OSError, ValueError) as exc:
            notice.update(Text(str(exc), style="bold rgb(255,105,180)"))
        finally:
            self._undoing = False
            self._confirm = ()
        await self._refresh_changes()

    async def action_undo_edit(self) -> None:
        await self._undo(False)

    async def action_undo_turn(self) -> None:
        await self._undo(True)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "undo-edit":
            await self.action_undo_edit()
        elif event.button.id == "undo-turn":
            await self.action_undo_turn()
        else:
            self.action_close()

    def action_close(self) -> None:
        if not self._undoing:
            self.dismiss(None)
