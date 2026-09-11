"""Exercise version checks, partial undo and TUI review without a model."""

import pytest
from textual.app import App
from textual.widgets import Static

from clanker.changes import ChangeConflictError, ChangeJournal, active_journal, change_actor
from clanker.tools.file_tools import append_file, edit_file, read_file, write_file
from clanker.ui.changes_panel import ChangesScreen


@pytest.fixture
def journal():
    journal = ChangeJournal()
    journal.begin_turn()
    token = active_journal.set(journal)
    yield journal
    active_journal.reset(token)


def test_undo_preserves_original_dirty_contents(journal, tmp_path):
    path = tmp_path / "file.py"
    path.write_text("user edit\n")
    read_file.invoke({"file_path": str(path)})
    assert write_file.invoke({"file_path": str(path), "content": "agent edit\n"})["ok"]
    assert journal.undo([1]) == 1
    assert path.read_text() == "user edit\n"
    assert journal.changes[0].undone


def test_stale_read_rejected_and_reread_recovers(journal, tmp_path):
    path = tmp_path / "file.py"
    path.write_text("original")
    read_file.invoke({"file_path": str(path)})
    path.write_text("external edit")
    result = write_file.invoke({"file_path": str(path), "content": "agent edit"})
    assert not result["ok"]
    assert path.read_text() == "external edit"
    assert not journal.changes
    read_file.invoke({"file_path": str(path)})
    assert write_file.invoke({"file_path": str(path), "content": "agent edit"})["ok"]


def test_undo_turn_preflights_all_files(journal, tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    journal.write(one, b"one")
    journal.write(two, b"two")
    one.write_bytes(b"external")
    with pytest.raises(ChangeConflictError):
        journal.undo([1, 2])
    assert two.read_bytes() == b"two"
    assert all(not c.undone for c in journal.changes)


def test_undo_edit_chain_and_new_file(journal, tmp_path):
    path = tmp_path / "new"
    journal.write(path, b"first")
    journal.write(path, b"second")
    with pytest.raises(ChangeConflictError):
        journal.undo([1])
    assert journal.undo([1, 2]) == 2
    assert not path.exists()


def test_symlink_swap_blocks_undo(journal, tmp_path):
    path, other = tmp_path / "one", tmp_path / "other"
    journal.write(path, b"agent")
    other.write_bytes(b"agent")
    path.unlink()
    path.symlink_to(other)
    with pytest.raises(ChangeConflictError):
        journal.undo([1])
    assert other.read_bytes() == b"agent"


def test_edit_append_and_preview_recorded(journal, tmp_path):
    path = tmp_path / "one"
    journal.write(path, b"a\r\nb\r\n")
    assert edit_file.invoke(
        {"file_path": str(path), "old_string": "b", "new_string": "c", "preview": True}
    )["ok"]
    assert len(journal.changes) == 1
    assert edit_file.invoke({"file_path": str(path), "old_string": "b", "new_string": "c"})["ok"]
    assert path.read_bytes() == b"a\r\nc\r\n"
    assert append_file.invoke({"file_path": str(path), "content": "d"})["ok"]
    assert len(journal.changes) == 3


def test_actor_reads_do_not_clobber_each_other(journal, tmp_path):
    path = tmp_path / "one"
    path.write_bytes(b"initial")
    journal.observe(path, b"initial")
    token = change_actor.set("child")
    journal.write(path, b"child")
    change_actor.reset(token)
    with pytest.raises(ChangeConflictError):
        journal.write(path, b"parent")


@pytest.mark.asyncio
async def test_panel_review_confirm_undo_and_busy_guard(journal, tmp_path):
    path = tmp_path / "file.py"
    path.write_bytes(b"before\n")
    journal.write(path, b"after\n")
    busy = [True]
    app = App()
    async with app.run_test(size=(100, 32)) as pilot:
        screen = ChangesScreen(journal, str(tmp_path), is_busy=lambda: busy[0])
        app.push_screen(screen)
        await pilot.pause()
        assert screen._selected().path == path
        await screen.action_undo_edit()
        assert path.read_bytes() == b"after\n"
        busy[0] = False
        await screen.action_undo_edit()
        assert "confirm" in str(screen.query_one("#changes-notice", Static).render())
        await screen.action_undo_edit()
        assert path.read_bytes() == b"before\n"
        await pilot.press("escape")
        assert app.screen is not screen


def test_undo_rolls_back_on_write_failure(journal, tmp_path, monkeypatch):
    import clanker.changes as module

    one, two = tmp_path / "one", tmp_path / "two"
    one.write_bytes(b"original one")
    two.write_bytes(b"original two")
    journal.write(one, b"agent one")
    journal.write(two, b"agent two")
    replace = module._replace

    def fail_second(path, content):
        if path == one and content == b"original one":
            raise OSError("disk error")
        replace(path, content)

    monkeypatch.setattr(module, "_replace", fail_second)
    with pytest.raises(OSError):
        journal.undo([1, 2])
    assert one.read_bytes() == b"agent one"
    assert two.read_bytes() == b"agent two"
    assert not any(c.undone for c in journal.changes)


def test_diff_marks_missing_newline(journal, tmp_path):
    path = tmp_path / "one"
    path.write_bytes(b"before")
    change = journal.write(path, b"after")
    assert "-before\n" in change.diff()
    assert "+after\n" in change.diff()
    assert "No newline at end of file" in change.diff()


def test_undo_notification_does_not_reinject_conversation():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from langchain_core.messages import HumanMessage

    from clanker.ui.app import ClankerApp

    original = HumanMessage(content="Original task")
    state = SimpleNamespace(
        _change_journal=ChangeJournal(),
        _conversation_messages=[original],
        _pending_restore_messages=[],
        _session_manager=MagicMock(),
    )
    ClankerApp._record_undo(state, (1,))
    assert len(state._pending_restore_messages) == 1
    assert original not in state._pending_restore_messages
    assert len(state._conversation_messages) == 2
