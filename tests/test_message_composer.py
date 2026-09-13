"""Exercise multiline editing through the real app and submission queue."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from textual import events
from textual.widgets import Button, Markdown, TabbedContent, TextArea

from clanker.ui.app import ClankerApp
from clanker.ui.clipboard_image import ClipboardImage
from clanker.ui.console import Console
from clanker.ui.message_composer import MessageComposer
from clanker.ui.prompt_history import PromptDraft


@pytest.mark.parametrize("discard", ["escape", "button"])
async def test_discard_preserves_original_draft_and_paste(discard):
    app = ClankerApp(Console())
    app._play_hero = AsyncMock()
    async with app.run_test(size=(100, 30)) as pilot:
        prompt = app.get_prompt_input()
        prompt.value = "Review [pasted 2 lines]"
        prompt._pending_pastes = [("[pasted 2 lines]", "one\ntwo")]
        await pilot.press("ctrl+up")
        assert isinstance(app.screen, MessageComposer)
        editor = app.screen.query_one(TextArea)
        assert editor.text == "Review one\ntwo"
        assert app.focused is editor
        editor.load_text("Unsent changes")
        if discard == "escape":
            await pilot.press("escape")
        else:
            await pilot.click("#composer-discard")
        assert prompt.value == "Review [pasted 2 lines]"
        assert prompt._pending_pastes == [("[pasted 2 lines]", "one\ntwo")]
        assert app.focused is prompt
        assert app._input_queue.empty()


@pytest.mark.parametrize("send", ["ctrl+enter", "button"])
async def test_markdown_preview_and_send_queue_exact_multiline_text(send):
    app = ClankerApp(Console())
    app._play_hero = AsyncMock()
    # Keep history writes inside the test rather than touching user history.
    app._save_history = lambda: None
    async with app.run_test(size=(100, 30)) as pilot:
        app._processing = True
        await pilot.press("f5")
        composer = app.screen
        assert isinstance(composer, MessageComposer)
        assert composer.query_one("#composer-send", Button).disabled
        await pilot.press("ctrl+enter")
        assert app.screen is composer
        editor = composer.query_one(TextArea)
        markdown = "# Request\n\n- **Keep formatting**\n\n```python\nprint('hello')\n```"
        editor.load_text(markdown)
        await pilot.pause()
        composer.query_one(TabbedContent).active = "composer-preview"
        await pilot.pause()
        assert composer.query_one(Markdown).query("MarkdownH1")
        if send == "button":
            await pilot.click("#composer-send")
        else:
            await pilot.press("ctrl+enter")
        assert not isinstance(app.screen, MessageComposer)
        assert app._input_queue.get_nowait() == markdown
        assert app.get_prompt_input().value == ""
        assert app.get_prompt_input()._pending_pastes == []


async def test_enter_inserts_newline_instead_of_sending():
    app = ClankerApp(Console())
    app._play_hero = AsyncMock()
    async with app.run_test(size=(60, 24)) as pilot:
        await pilot.press("ctrl+up", "a", "enter", "b")
        assert isinstance(app.screen, MessageComposer)
        assert app.screen.query_one(TextArea).text == "a\nb"
        assert app.screen.query_one("#composer-send").region.bottom <= 24
        await pilot.press("escape")


async def test_composer_image_paste_send_recall_and_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    image = ClipboardImage(b"test image bytes", "image/png")
    monkeypatch.setattr("clanker.ui.message_composer.read_clipboard_image", lambda: image)
    app = ClankerApp(Console())
    app._play_hero = AsyncMock()
    app._run_agent = AsyncMock()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("f5")
        editor = app.screen.query_one(TextArea)
        editor.post_message(events.Paste("# Request\r\n\r\nLook at this:\r"))
        await pilot.pause()
        # A stale in-app clipboard must not hide a newly copied OS image.
        app.copy_to_clipboard("stale text")
        await pilot.press("ctrl+v")
        await app.screen.workers.wait_for_complete()
        await pilot.pause()
        expected = "# Request\n\nLook at this:\n[Image #1]"
        assert editor.text == expected
        await pilot.press("ctrl+enter")
        await pilot.pause()
        app._run_agent.assert_awaited_once_with(expected, [image])
        await pilot.press("up")
        prompt = app.get_prompt_input()
        assert prompt.snapshot_draft().expanded_text() == expected
        assert prompt._pending_images == [("[Image #1]", image)]
        await pilot.press("f5")
        assert app.screen.query_one(TextArea).text == expected
        await pilot.press("escape")

    restarted = ClankerApp(Console())
    restarted._play_hero = AsyncMock()
    async with restarted.run_test(size=(100, 30)) as pilot:
        await pilot.press("up", "f5")
        assert restarted.screen.query_one(TextArea).text == expected
        assert restarted.screen._images == [("[Image #1]", image)]
        await pilot.press("escape")


async def test_new_images_discarded_and_deleted_markers_not_sent(monkeypatch):
    image = ClipboardImage(b"new image", "image/png")
    old_image = ClipboardImage(b"old image", "image/png")
    monkeypatch.setattr("clanker.ui.message_composer.read_clipboard_image", lambda: image)
    app = ClankerApp(Console())
    app._play_hero = AsyncMock()
    app._save_history = lambda: None
    app._run_agent = AsyncMock()
    async with app.run_test(size=(100, 30)) as pilot:
        prompt = app.get_prompt_input()
        original = PromptDraft("Original [Image #1]", images=[("[Image #1]", old_image)])
        prompt.restore_draft(original)
        await pilot.press("f5")
        app.screen.query_one(TextArea).post_message(events.Paste(""))
        await pilot.pause()
        await app.screen.workers.wait_for_complete()
        assert len(app.screen._images) == 2
        await pilot.press("escape")
        assert prompt.snapshot_draft() == original
        await pilot.press("f5")
        editor = app.screen.query_one(TextArea)
        editor.load_text("Replacement: ")
        editor.move_cursor((0, len(editor.text)))
        await pilot.press("ctrl+v")
        await app.screen.workers.wait_for_complete()
        await pilot.pause()
        assert editor.text == "Replacement: [Image #2]"
        await pilot.press("ctrl+enter")
        await pilot.pause()
        app._run_agent.assert_awaited_once_with("Replacement: [Image #2]", [image])


async def test_history_navigation_restores_pending_draft_and_duplicate_pastes():
    app = ClankerApp(Console())
    app._play_hero = AsyncMock()
    app._save_history = lambda: None
    async with app.run_test() as pilot:
        prompt = app.get_prompt_input()
        original = PromptDraft("[pasted 2 lines] [pasted 2 lines]", pastes=[
            ("[pasted 2 lines]", "one\ntwo"), ("[pasted 2 lines]", "three\nfour")
        ])
        prompt.restore_draft(original)
        app._processing = True
        await pilot.press("enter")
        pending = PromptDraft("[pasted 2 lines]", pastes=[("[pasted 2 lines]", "unsent\ndraft")])
        prompt.restore_draft(pending)
        await pilot.press("up")
        assert prompt.snapshot_draft() == original
        await pilot.press("down")
        assert prompt.snapshot_draft() == pending
        await pilot.press("up", "enter")
        assert app._input_queue.get_nowait() == "one\ntwo three\nfour"
        assert app._input_queue.get_nowait() == "one\ntwo three\nfour"


def test_legacy_history_is_loaded(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".clanker").mkdir()
    (tmp_path / ".clanker" / "input_history.txt").write_text("first prompt\nsecond prompt\n")
    app = ClankerApp(Console())
    assert [draft.text for draft in app._input_history] == ["first prompt", "second prompt"]


async def test_composer_arrow_history_preserves_cursor_navigation_draft_and_images():
    app = ClankerApp(Console())
    app._play_hero = AsyncMock()
    image = ClipboardImage(b"history image", "image/png")
    async with app.run_test(size=(100, 30)) as pilot:
        prompt = app.get_prompt_input()
        prompt.set_history([
            PromptDraft("older"),
            PromptDraft("[pasted 2 lines]", pastes=[("[pasted 2 lines]", "latest\n[Image #1]")],
                        images=[("[Image #1]", image)]),
        ])
        prompt.value = "unsent draft"
        await pilot.press("f5", "up")
        composer = app.screen
        editor = composer.query_one(TextArea)
        assert editor.text == "latest\n[Image #1]"
        assert composer._images == [("[Image #1]", image)]
        editor.move_cursor((1, 0))
        await pilot.press("up")
        assert editor.cursor_location == (0, 0)
        assert editor.text == "latest\n[Image #1]"
        await pilot.press("up")
        assert editor.text == "older"
        assert composer._images == []
        editor.move_cursor((0, 5))
        await pilot.press("down")
        assert editor.text == "latest\n[Image #1]"
        assert composer._images == [("[Image #1]", image)]
        await pilot.press("down")
        assert editor.text == "unsent draft"
        await pilot.press("escape")
        assert prompt.value == "unsent draft"


async def test_composer_up_with_no_history_and_shift_selection_are_normal():
    app = ClankerApp(Console())
    app._play_hero = AsyncMock()
    async with app.run_test(size=(60, 24)) as pilot:
        app.get_prompt_input().set_history([])
        await pilot.press("f5", "up")
        editor = app.screen.query_one(TextArea)
        assert editor.text == ""
        editor.load_text("first\nsecond")
        editor.move_cursor((1, 3))
        await pilot.press("shift+up")
        assert not editor.selection.is_empty
        assert editor.text == "first\nsecond"
        await pilot.press("escape")
