"""Selection is safe after reveals and unavailable while blocks are changing."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from textual import events
from textual.geometry import Offset
from textual.widgets import Markdown

from clanker.ui.app import ClankerApp
from clanker.ui.chat_log import MessageType
from clanker.ui.console import Console


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(ClankerApp, "_load_history", lambda self: [])
    monkeypatch.setattr(ClankerApp, "_save_history", lambda self: None)
    application = ClankerApp(Console())
    application._play_hero = AsyncMock()
    return application


@pytest.mark.asyncio
async def test_mouse_down_ignores_removed_markdown_block(app, monkeypatch):
    async with app.run_test(size=(100, 30)) as pilot:
        markdown = Markdown("Selectable text")
        await app.get_chat_log().mount(markdown)
        await pilot.pause()
        block = markdown.query_one("MarkdownParagraph")
        await block.remove()
        assert block.parent is None
        # A compositor frame can still contain a block removed by Markdown.update.
        monkeypatch.setattr(
            app.screen._compositor, "get_widget_and_offset_at", lambda x, y: (block, Offset(0, 0))
        )
        event = events.MouseDown(None, 1, 1, 0, 0, 1, False, False, False)
        app.screen._forward_event(event)
        assert app.screen._select_state is None


@pytest.mark.asyncio
async def test_drag_ignores_block_removed_after_mouse_down(app, monkeypatch):
    async with app.run_test(size=(100, 30)) as pilot:
        markdown = Markdown("Selectable text")
        await app.get_chat_log().mount(markdown)
        await pilot.pause()
        block = markdown.query_one("MarkdownParagraph")
        await pilot.mouse_down(block)
        assert app.screen._select_state is not None
        await block.remove()
        monkeypatch.setattr(
            app.screen._compositor, "get_widget_and_offset_at", lambda x, y: (block, Offset(4, 0))
        )
        app.screen._forward_event(events.MouseMove(None, 5, 1, 4, 0, 1, False, False, False))
        app.screen._forward_event(events.MouseUp(None, 5, 1, 0, 0, 1, False, False, False))
        assert not app.screen._selecting


@pytest.mark.asyncio
@pytest.mark.parametrize("remove_message", [False, True])
async def test_selection_is_enabled_only_after_reveal(app, monkeypatch, remove_message):
    full_text = "Copy this selectable paragraph while the rest is revealed. " * 20
    first_update = asyncio.Event()
    continue_updates = asyncio.Event()
    original_update = Markdown.update

    async def update(widget, content):
        await original_update(widget, content)
        if content and not first_update.is_set():
            first_update.set()
            await continue_updates.wait()

    monkeypatch.setattr(Markdown, "update", update)
    async with app.run_test(size=(100, 30)) as pilot:
        app.get_chat_log().add_message(full_text, MessageType.ASSISTANT)
        await asyncio.wait_for(first_update.wait(), timeout=2)
        await pilot.pause()
        markdown = app.get_chat_log().query_one(".msg-assistant", Markdown)
        block = markdown.query_one("MarkdownParagraph")
        prefix = markdown.source
        assert prefix and prefix != full_text
        assert not app.screen.allow_select
        origin = block.region.offset
        await pilot.mouse_down(block, offset=(0, 0))
        await pilot.hover(block, offset=(8, 0))
        assert app.screen._select_state is None
        assert not app.screen.get_selected_text()
        if remove_message:
            await markdown.remove()
        continue_updates.set()
        # Holding the mouse down must not pause the animation.
        await asyncio.wait_for(app.workers.wait_for_complete(), timeout=5)
        assert app.screen.allow_select
        await pilot.mouse_up(offset=(origin.x + 8, origin.y))
        if remove_message:
            assert not markdown.is_attached
            replacement = "A new response after the selected message was removed."
            app.get_chat_log().add_message(replacement, MessageType.ASSISTANT)
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=5)
            assert app.get_chat_log().query_one(".msg-assistant", Markdown).source == replacement
        else:
            assert markdown.source == full_text
            block = markdown.query_one("MarkdownParagraph")
            await pilot.mouse_down(block, offset=(0, 0))
            await pilot.hover(block, offset=(8, 0))
            await pilot.mouse_up(block, offset=(8, 0))
            selected = app.screen.get_selected_text()
            assert selected and "Copy this" in selected
            clipboard = MagicMock()
            monkeypatch.setattr(app, "copy_to_clipboard", clipboard)
            app.action_copy_or_interrupt()
            clipboard.assert_called_once_with(selected)


@pytest.mark.asyncio
async def test_overlapping_reveals_keep_selection_disabled_until_both_finish(app, monkeypatch):
    started = {char: asyncio.Event() for char in "AB"}
    release = {char: asyncio.Event() for char in "AB"}
    finished_first = asyncio.Event()
    original_update = Markdown.update

    async def update(widget, content):
        await original_update(widget, content)
        char = content[:1]
        if char in started and not started[char].is_set():
            started[char].set()
            await release[char].wait()
        if content == "A" * 80:
            finished_first.set()

    monkeypatch.setattr(Markdown, "update", update)
    async with app.run_test(size=(100, 30)) as pilot:
        app.get_chat_log().add_message("A" * 80, MessageType.ASSISTANT)
        app.get_chat_log().add_message("B" * 80, MessageType.ASSISTANT)
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), 2)
        assert not app.screen.allow_select
        release["A"].set()
        await asyncio.wait_for(finished_first.wait(), 5)
        await pilot.pause(0.05)
        assert not app.screen.allow_select
        release["B"].set()
        await asyncio.wait_for(app.workers.wait_for_complete(), 5)
        assert app.screen.allow_select
