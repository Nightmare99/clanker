"""Long-term memory remains editable, searchable, and compatible with old files."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from textual.widgets import Input, ListView, Static, TextArea

from clanker.memory.index import fts5_available
from clanker.memory.memories import MemoryKind, MemorySource, MemoryStore
from clanker.tools.memory_tools import forget, list_memories, recall, remember, revise_memory
from clanker.tools.subagent import _resolve_tools
from clanker.ui.app import ClankerApp
from clanker.ui.console import Console
from clanker.ui.memory_screen import MemoryScreen
from clanker.ui.shortcut_help import ShortcutHelpScreen


def test_existing_markdown_is_loaded_without_rewriting(tmp_path):
    path = tmp_path / ".clanker" / "memories" / "a1b2c3d4.md"
    path.parent.mkdir(parents=True)
    original = "---\nid: a1b2c3d4\nsource: user\ncreated: 2026-08-21T10:15:00\ntags: [convention, testing]\n---\n\nUse pytest."
    path.write_text(original)

    memory, = MemoryStore(tmp_path).list_all()
    assert memory.id == "a1b2c3d4"
    assert memory.content == "Use pytest."
    assert memory.tags == ["convention", "testing"]
    assert memory.kind == MemoryKind.FACT
    assert path.read_text() == original


def test_upsert_revision_provenance_and_credentials(tmp_path):
    store = MemoryStore(tmp_path)
    first = store.add(
        "Use uv for dependencies", source=MemorySource.USER,
        kind="preference", tags=["tooling"], evidence="pyproject.toml",
        metadata={"conversation": "abc12345"}, pinned=True,
    )
    assert store.add("  use UV for dependencies  ").id == first.id
    reloaded = store.get(first.id)
    assert reloaded is not None
    assert reloaded.metadata == {"conversation": "abc12345"}
    assert reloaded.evidence == "pyproject.toml"
    assert reloaded.pinned

    revised = store.supersede(first.id, "Use Poetry for dependencies", evidence="README.md")
    assert revised.id != first.id
    assert store.get(first.id).status == "stale"
    assert store.get(revised.id).metadata["supersedes"] == first.id
    assert [m.id for m in store.search("dependencies")] == [revised.id]
    assert store.get(first.id) is not None  # Revision history remains inspectable.
    with pytest.raises(ValueError, match="Credential"):
        store.add("api_key = super-secret-value")
    assert not store.delete("../../outside")


def test_duplicate_user_memory_upgrades_auto_note(tmp_path):
    store = MemoryStore(tmp_path)
    auto = store.add("Use pytest for tests", source=MemorySource.AUTO)
    explicit = store.add(
        "Use pytest for tests", source=MemorySource.USER,
        tags=["testing"], pinned=True, kind="preference",
    )
    assert explicit.id == auto.id
    saved = store.get(auto.id)
    assert saved.source == MemorySource.USER
    assert saved.tags == ["testing"]
    assert saved.pinned
    assert saved.kind == MemoryKind.PREFERENCE


def test_global_preference_is_explicit_and_shared(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    first = MemoryStore(tmp_path / "project-a")
    memory = first.add("Prefer concise answers", kind="preference", scope="global")
    second = MemoryStore(tmp_path / "project-b")
    assert second.get(memory.id).content == "Prefer concise answers"
    assert memory.id in [m.id for m in second.search("answers")]
    second.delete(memory.id)
    assert first.get(memory.id) is None


def test_fts_index_tracks_external_edits_and_has_lexical_fallback(tmp_path, monkeypatch):
    store = MemoryStore(tmp_path)
    memory = store.add("Auth handler lives in src/service.py", tags=["architecture"])
    assert fts5_available()
    assert [m.id for m in store.search("auth handler")] == [memory.id]
    assert (tmp_path / ".clanker" / "memory-index.sqlite").exists()

    path = tmp_path / ".clanker" / "memories" / f"{memory.id}.md"
    path.write_text(path.read_text().replace("Auth handler", "Login handler"))
    assert [m.id for m in store.search("login handler")] == [memory.id]
    assert store.search("auth") == []

    monkeypatch.setattr(store._index, "search", lambda query, documents: None)
    assert [m.id for m in store.search("login handler")] == [memory.id]


def test_context_is_bounded_and_excludes_stale_notes(tmp_path):
    store = MemoryStore(tmp_path)
    old = store.add("Use the old deployment script", tags=["deploy"])
    store.update(old.id, status="stale")
    store.add("Use the new deployment script " + "details " * 500, tags=["deploy"])
    context = store.get_relevant_context("deployment script", token_budget=100)
    assert "old deployment" not in context
    assert "new deployment" in context
    assert len(context) < 650


def test_repository_evidence_change_requires_reverification(tmp_path):
    source = tmp_path / "README.md"
    source.write_text("Original architecture")
    store = MemoryStore(tmp_path)
    memory = store.add("Architecture lives in README", evidence="README.md")
    assert [m.id for m in store.search("architecture")] == [memory.id]
    source.write_text("Revised architecture with more details")
    assert store.needs_verification(store.get(memory.id))
    assert store.search("architecture") == []
    store.update(memory.id, verified_at="2026-09-28T00:00:00+00:00")
    assert [m.id for m in store.search("architecture")] == [memory.id]
    store.update(memory.id, evidence="https://example.com/architecture")
    assert not store.needs_verification(store.get(memory.id))
    assert [m.id for m in store.search("architecture")] == [memory.id]


def test_subagents_can_recall_but_cannot_edit_memory(monkeypatch):
    monkeypatch.setattr(
        "clanker.tools.get_tools",
        lambda: [remember, recall, revise_memory, forget, list_memories],
    )
    names = {tool.name for tool in _resolve_tools([])}
    assert {"recall", "list_memories"} <= names
    assert not {"remember", "revise_memory", "forget"} & names


async def test_memory_tui_can_edit_pin_and_forget(tmp_path):
    store = MemoryStore(tmp_path)
    memory = store.add("Initial convention", tags=["testing"])
    app = ClankerApp(Console())
    app._play_hero = AsyncMock()
    async with app.run_test(size=(120, 38)) as pilot:
        app.push_screen(MemoryScreen(store))
        await pilot.pause()
        screen = app.screen
        assert screen.query_one("#memory-list", ListView).children
        await pilot.click("#memory-pin")
        assert store.get(memory.id).pinned

        await pilot.click("#memory-edit")
        screen.query_one("#memory-editor", TextArea).load_text("Updated convention")
        screen.query_one("#memory-tags", Input).value = "testing, architecture"
        await pilot.click("#memory-save")
        assert store.get(memory.id).content == "Updated convention"
        assert store.get(memory.id).tags == ["testing", "architecture"]

        await pilot.click("#memory-forget")
        assert store.get(memory.id) is not None
        assert screen._pending_delete == memory.id
        await pilot.click("#memory-confirm-delete")
        assert screen._pending_delete is None
        assert store.get(memory.id) is None
        await pilot.press("escape")
        assert app.screen is not screen


async def test_f6_opens_memories_and_f1_help_lists_shortcut(tmp_path):
    app = ClankerApp(Console())
    app._play_hero = AsyncMock()
    app._working_dir = str(tmp_path)
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.press("f6")
        assert isinstance(app.screen, MemoryScreen)
        assert app.screen.store._storage.workspace_path == tmp_path
        await pilot.press("escape", "f1")
        assert isinstance(app.screen, ShortcutHelpScreen)
        help_text = str(app.screen.query_one(Static).render())
        assert "F6" in help_text and "Memories" in help_text
