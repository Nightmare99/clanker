"""Search and curate long-term memories without leaving the TUI."""

from __future__ import annotations

from datetime import UTC, datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, ListItem, ListView, Static, TextArea

from clanker.memory.memories import Memory, MemoryKind, MemoryStore


class MemoryScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Close", priority=True)]

    DEFAULT_CSS = """
    MemoryScreen { align: center middle; }
    MemoryScreen #memory-modal {
        width: 88%; height: 85%; border: round rgb(0,240,240);
        background: black; padding: 1 2;
    }
    MemoryScreen #memory-title { height: 1; color: rgb(0,240,240); text-style: bold; }
    MemoryScreen #memory-search { height: 3; }
    MemoryScreen #memory-main { height: 1fr; }
    MemoryScreen #memory-list { width: 42%; height: 1fr; margin-right: 2; }
    MemoryScreen #memory-detail { width: 1fr; height: 1fr; }
    MemoryScreen #memory-preview { height: 1fr; color: rgb(200,200,200); }
    MemoryScreen #memory-editor { height: 1fr; }
    MemoryScreen #memory-tags { height: 3; }
    MemoryScreen #memory-status { height: 2; color: rgb(140,140,140); }
    MemoryScreen #memory-actions { height: 3; }
    MemoryScreen Button { margin-right: 1; }
    """

    def __init__(self, store: MemoryStore) -> None:
        super().__init__()
        self.store = store
        self._rows: list[Memory] = []
        self._selected_id: str | None = None
        self._editing = False
        self._adding = False
        self._kind = MemoryKind.FACT
        self._scope = "workspace"
        self._pending_delete: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="memory-modal"):
            yield Static("Memories · search, inspect, and curate", id="memory-title")
            yield Input(placeholder="Search content, tags, source, or ID", id="memory-search")
            with Horizontal(id="memory-main"):
                yield ListView(id="memory-list")
                with Vertical(id="memory-detail"):
                    yield Static("Select a memory to inspect it.", id="memory-preview")
                    yield TextArea("", language="markdown", soft_wrap=True, id="memory-editor")
                    yield Input(placeholder="Tags, separated by commas", id="memory-tags")
            yield Static("User memories take precedence over inferred notes. Esc closes or discards an edit.", id="memory-status")
            with Horizontal(id="memory-actions"):
                yield Button("Add", id="memory-add")
                yield Button("Edit", id="memory-edit")
                yield Button("Pin", id="memory-pin")
                yield Button("Verify", id="memory-verify")
                yield Button("Stale", id="memory-stale")
                yield Button("Forget", id="memory-forget")
                yield Button("Delete now", id="memory-confirm-delete", variant="error")
                yield Button("Close", id="memory-close")
                yield Button("Save", id="memory-save", variant="primary")
                yield Button("Kind: fact", id="memory-kind")
                yield Button("Scope: workspace", id="memory-scope")
                yield Button("Discard", id="memory-discard")

    async def on_mount(self) -> None:
        self._show_editor(False)
        await self._refresh()
        self.query_one("#memory-list", ListView).focus()

    def _show_editor(self, visible: bool) -> None:
        self._editing = visible
        self.query_one("#memory-preview", Static).display = not visible
        for widget_id in ("memory-editor", "memory-tags", "memory-save", "memory-kind", "memory-scope", "memory-discard"):
            self.query_one(f"#{widget_id}").display = visible
        for widget_id in ("memory-add", "memory-edit", "memory-pin", "memory-verify", "memory-stale", "memory-forget", "memory-close"):
            self.query_one(f"#{widget_id}").display = not visible
        self.query_one("#memory-scope", Button).disabled = visible and not self._adding
        self._render_delete_confirmation()

    def _render_delete_confirmation(self) -> None:
        confirming = not self._editing and self._pending_delete is not None
        self.query_one("#memory-forget", Button).display = not self._editing and not confirming
        self.query_one("#memory-confirm-delete", Button).display = confirming

    async def _refresh(self) -> None:
        query = self.query_one("#memory-search", Input).value.casefold().strip()
        memories = self.store.list_all(limit=None)
        self._rows = [
            memory for memory in memories
            if not query or query in " ".join((
                memory.content, " ".join(memory.tags), memory.id,
                memory.source.value, memory.kind.value, memory.evidence or "",
            )).casefold()
        ]
        view = self.query_one("#memory-list", ListView)
        await view.clear()
        for memory in self._rows:
            prefix = "★ " if memory.pinned else ""
            suffix = " · stale" if memory.status != "active" else ""
            title = " ".join(memory.content.split())[:65]
            await view.append(ListItem(Static(f"{prefix}{title}\n{memory.id} · {memory.kind.value} · {memory.scope}{suffix}")))
        if self._rows:
            selected = next((i for i, memory in enumerate(self._rows) if memory.id == self._selected_id), 0)
            view.index = selected
            self._selected_id = self._rows[selected].id
        else:
            self._selected_id = None
        self._show_preview()

    def _selected(self) -> Memory | None:
        return next((memory for memory in self._rows if memory.id == self._selected_id), None)

    def _show_preview(self) -> None:
        memory = self._selected()
        if memory is None:
            self.query_one("#memory-preview", Static).update("No matching memories.")
            return
        verified = memory.verified_at[:16] if memory.verified_at else "never"
        evidence = memory.evidence or "none recorded"
        query = self.query_one("#memory-search", Input).value.casefold().strip()
        if query and any(query in tag.casefold() for tag in memory.tags):
            reason = "matched tag"
        elif query and query in memory.content.casefold():
            reason = "matched content"
        elif query:
            reason = "matched metadata"
        else:
            reason = "browsing all memories"
        state = "needs verification" if self.store.needs_verification(memory) else memory.status
        preview = (
            f"{memory.content}\n\n"
            f"ID {memory.id} · {memory.kind.value} · {memory.scope} · {memory.source.value}\n"
            f"Tags: {', '.join(memory.tags) or 'none'}\n"
            f"Verified: {verified} · Status: {state}\n"
            f"Evidence: {evidence}\n"
            f"Shown because: {reason}"
        )
        self.query_one("#memory-preview", Static).update(preview)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "memory-list" or self._editing:
            return
        index = event.list_view.index
        if index is not None and 0 <= index < len(self._rows):
            selected_id = self._rows[index].id
            if selected_id != self._selected_id:
                self._pending_delete = None
                self._render_delete_confirmation()
            self._selected_id = selected_id
            self._show_preview()

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "memory-search":
            await self._refresh()

    def _start_edit(self, adding: bool) -> None:
        memory = None if adding else self._selected()
        if memory is None and not adding:
            return
        self._adding = adding
        self._kind = memory.kind if memory else MemoryKind.FACT
        self._scope = memory.scope if memory else "workspace"
        self.query_one("#memory-editor", TextArea).load_text(memory.content if memory else "")
        self.query_one("#memory-tags", Input).value = ", ".join(memory.tags) if memory else ""
        self.query_one("#memory-kind", Button).label = f"Kind: {self._kind.value}"
        self.query_one("#memory-scope", Button).label = f"Scope: {self._scope}"
        self._show_editor(True)
        self.query_one("#memory-editor", TextArea).focus()

    async def _save_edit(self) -> None:
        content = self.query_one("#memory-editor", TextArea).text.strip()
        tags = [tag.strip() for tag in self.query_one("#memory-tags", Input).value.split(",") if tag.strip()]
        memory: Memory | None
        try:
            if self._adding:
                memory = self.store.add(content, tags=tags, kind=self._kind, scope=self._scope)
            else:
                memory = self.store.update(self._selected_id or "", content=content, tags=tags, kind=self._kind)
        except ValueError as exc:
            self.query_one("#memory-status", Static).update(str(exc))
            return
        self._selected_id = memory.id if memory else None
        self._show_editor(False)
        self.query_one("#memory-status", Static).update("Memory saved.")
        await self._refresh()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        action = event.button.id
        memory = self._selected()
        if action == "memory-close":
            self.action_close()
        elif action == "memory-add":
            self._start_edit(True)
        elif action == "memory-edit":
            self._start_edit(False)
        elif action == "memory-discard":
            self._show_editor(False)
            self._show_preview()
        elif action == "memory-kind":
            kinds = list(MemoryKind)
            self._kind = kinds[(kinds.index(self._kind) + 1) % len(kinds)]
            event.button.label = f"Kind: {self._kind.value}"
        elif action == "memory-scope" and self._adding:
            self._scope = "global" if self._scope == "workspace" else "workspace"
            event.button.label = f"Scope: {self._scope}"
        elif action == "memory-save":
            await self._save_edit()
        elif memory and action == "memory-pin":
            self.store.update(memory.id, pinned=not memory.pinned)
            await self._refresh()
        elif memory and action == "memory-verify":
            self.store.update(memory.id, verified_at=datetime.now(UTC).isoformat())
            await self._refresh()
        elif memory and action == "memory-stale":
            self.store.update(memory.id, status="active" if memory.status == "stale" else "stale")
            await self._refresh()
        elif memory and action == "memory-forget":
            self._pending_delete = memory.id
            self._render_delete_confirmation()
            self.query_one("#memory-status", Static).update("Delete this memory permanently?")
        elif memory and action == "memory-confirm-delete" and self._pending_delete == memory.id:
            self.store.delete(memory.id)
            self._pending_delete = None
            self._render_delete_confirmation()
            self.query_one("#memory-status", Static).update("Memory deleted.")
            await self._refresh()

    def action_close(self) -> None:
        if self._editing:
            self._show_editor(False)
        elif self.app.screen is self:
            self.dismiss(None)
