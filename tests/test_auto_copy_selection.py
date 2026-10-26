"""Selection reaches the clipboard on every platform without a copy shortcut."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from textual.screen import ModalScreen
from textual.widgets import Markdown

from clanker.ui import keyboard
from clanker.ui.app import ClankerApp
from clanker.ui.chat_log import MessageType
from clanker.ui.console import Console


@pytest.fixture(params=[True, False], ids=["macos", "other-platforms"])
def app(monkeypatch, request):
    monkeypatch.setattr(keyboard, "is_macos", lambda: request.param)
    monkeypatch.setattr(ClankerApp, "_load_history", lambda self: [])
    monkeypatch.setattr(ClankerApp, "_save_history", lambda self: None)
    monkeypatch.setattr(ClankerApp, "_refresh_selected_model", lambda self: None)
    application = ClankerApp(Console())
    application._play_hero = AsyncMock()
    application.action_interrupt = MagicMock()
    return application


@pytest.mark.parametrize("modal", [False, True])
async def test_drag_copies_on_release_without_a_copy_shortcut(app, modal):
    async with app.run_test(size=(100, 30)) as pilot:
        if modal:
            await app.push_screen(ModalScreen())
            container = app.screen
        else:
            container = app.get_chat_log()
        markdown = Markdown("Copy this paragraph seamlessly")
        await container.mount(markdown)
        await pilot.pause()
        app.copy_to_clipboard("old clipboard")
        block = markdown.query_one("MarkdownParagraph")
        await pilot.mouse_down(block, offset=(0, 0))
        await pilot.hover(block, offset=(8, 0))
        await pilot.pause()
        assert app.clipboard == "old clipboard"
        await pilot.mouse_up(block, offset=(8, 0))
        await pilot.pause()
        selected = app.screen.get_selected_text()
        assert selected and "Copy this" in selected
        assert app.clipboard == selected
        app.action_interrupt.assert_not_called()
        if modal:
            app.screen.dismiss()


@pytest.mark.parametrize("composer", [False, True])
async def test_keyboard_selection_in_editors_copies_without_command_c(app, composer):
    async with app.run_test(size=(100, 30)) as pilot:
        prompt = app.get_prompt_input()
        prompt.value = "Keyboard selected text"
        if composer:
            await pilot.press("f5")
        editor = app.focused
        await pilot.press("end", "shift+home")
        await pilot.pause()
        assert editor.selected_text == "Keyboard selected text"
        assert app.clipboard == "Keyboard selected text"
        # A cleared selection must leave the existing clipboard intact.
        await pilot.press("right")
        assert app.clipboard == "Keyboard selected text"
        if composer:
            await pilot.press("escape")


async def test_mouse_selection_in_prompt_copies_only_on_release(app):
    async with app.run_test(size=(100, 30)) as pilot:
        prompt = app.get_prompt_input()
        prompt.value = "Copy this input text"
        await pilot.pause()
        app.copy_to_clipboard("old clipboard")
        await pilot.mouse_down(prompt, offset=(0, 0))
        await pilot.hover(prompt, offset=(8, 0))
        await pilot.pause()
        assert app.clipboard == "old clipboard"
        await pilot.mouse_up(prompt, offset=(8, 0))
        await pilot.pause()
        assert prompt.selected_text
        assert app.clipboard == prompt.selected_text


@pytest.mark.parametrize("app", [True], indirect=True, ids=["macos"])
async def test_mouse_selection_reaches_native_clipboard_without_command_c(app, monkeypatch):
    from clanker.ui import native_clipboard

    write = AsyncMock(return_value=True)
    monkeypatch.setattr(native_clipboard, "is_local_macos", lambda: True)
    monkeypatch.setattr(native_clipboard, "write_text", write)
    async with app.run_test(size=(100, 30)) as pilot:
        markdown = Markdown("System clipboard without a key mapping")
        await app.get_chat_log().mount(markdown)
        await pilot.pause()
        # Exercise the production clipboard branch without touching macOS.
        monkeypatch.setattr(type(app._driver), "is_headless", property(lambda self: False))
        block = markdown.query_one("MarkdownParagraph")
        await pilot.mouse_down(block)
        await pilot.hover(block, offset=(8, 0))
        await pilot.pause()
        write.assert_not_awaited()
        await pilot.mouse_up(block, offset=(8, 0))
        await pilot.pause()
        await app.workers.wait_for_complete()
        selected = app.screen.get_selected_text()
        assert selected and selected.startswith("System")
        write.assert_awaited_once_with(selected)


@pytest.mark.parametrize("app", [False], indirect=True, ids=["other-platforms"])
async def test_selection_writes_terminal_clipboard_on_other_platforms(app, monkeypatch):
    import base64

    from clanker.ui import native_clipboard

    native_write = AsyncMock()
    monkeypatch.setattr(native_clipboard, "write_text", native_write)
    async with app.run_test(size=(100, 30)) as pilot:
        terminal_write = MagicMock()
        monkeypatch.setattr(app._driver, "write", terminal_write)
        markdown = Markdown("Copy through the terminal clipboard")
        await app.get_chat_log().mount(markdown)
        await pilot.pause()
        block = markdown.query_one("MarkdownParagraph")
        await pilot.mouse_down(block)
        await pilot.hover(block, offset=(8, 0))
        await pilot.mouse_up(block, offset=(8, 0))
        await pilot.pause()
        selected = app.screen.get_selected_text()
        assert selected and selected.startswith("Copy")
        payload = base64.b64encode(selected.encode("utf-8")).decode("ascii")
        terminal_write.assert_any_call(f"\x1b]52;c;{payload}\a")
        native_write.assert_not_awaited()


async def test_password_selection_does_not_copy_automatically(app):
    async with app.run_test() as pilot:
        prompt = app.get_prompt_input()
        prompt.password = True
        prompt.value = "private input"
        app.copy_to_clipboard("old clipboard")
        await pilot.press("end", "shift+home")
        await pilot.pause()
        assert prompt.selected_text == "private input"
        assert app.clipboard == "old clipboard"


async def test_copy_toast_is_compact_themed_and_counts_characters(app):
    from textual.color import Color

    async with app.run_test(size=(100, 30), notifications=True) as pilot:
        markdown = Markdown("Copy this paragraph")
        await app.get_chat_log().mount(markdown)
        await pilot.pause()
        block = markdown.query_one("MarkdownParagraph")
        await pilot.mouse_down(block)
        await pilot.hover(block, offset=(8, 0))
        assert not app.screen.query("Toast")
        await pilot.mouse_up(block, offset=(8, 0))
        await pilot.pause()
        selected = app.screen.get_selected_text()
        toast = app.screen.query_one("Toast")
        assert str(toast.render()) == f"Copied {len(selected)} characters"
        assert toast.region.height == 1
        assert toast.region.width < 40
        assert toast.styles.background == Color.parse(app.get_css_variables()["surface"])
        assert toast.styles.color == Color.parse(app.get_css_variables()["foreground"])
        assert toast.styles.border_left[1] == Color.parse(app.get_css_variables()["success"])
        await pilot.pause(1.6)
        assert not app.screen.query("Toast")


async def test_unicode_copy_toast_counts_characters_not_bytes(app):
    async with app.run_test(size=(100, 30), notifications=True) as pilot:
        text = "Hi 😀 café"
        app.get_prompt_input().value = text
        await pilot.press("end", "shift+home")
        await pilot.pause()
        toast = app.screen.query_one("Toast")
        assert str(toast.render()) == f"Copied {len(text)} characters"


@pytest.mark.parametrize("app", [True], indirect=True, ids=["macos"])
@pytest.mark.parametrize("success", [False, True])
async def test_native_copy_toast_waits_for_clipboard_result(app, monkeypatch, success):
    from clanker.ui import native_clipboard

    started = asyncio.Event()
    release = asyncio.Event()

    async def write(_):
        started.set()
        await release.wait()
        return success

    monkeypatch.setattr(native_clipboard, "is_local_macos", lambda: True)
    monkeypatch.setattr(native_clipboard, "write_text", write)
    async with app.run_test(size=(100, 30), notifications=True) as pilot:
        monkeypatch.setattr(type(app._driver), "is_headless", property(lambda self: False))
        app.copy_to_clipboard("😀")
        await asyncio.wait_for(started.wait(), 2)
        await pilot.pause()
        assert not app.screen.query("Toast")
        release.set()
        await asyncio.wait_for(app.workers.wait_for_complete(), 2)
        await pilot.pause()
        toast = app.screen.query_one("Toast")
        if success:
            assert str(toast.render()) == "Copied 1 character"
            assert toast.has_class("-information")
        else:
            assert "Native clipboard copy failed" in str(toast.render())
            assert toast.has_class("-warning")


async def test_reveal_finishes_before_selection_can_copy(app, monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    original_update = Markdown.update
    full_text = "Select this response after revealing finishes. " * 20

    async def update(widget, content):
        await original_update(widget, content)
        if content and not started.is_set():
            started.set()
            await release.wait()

    monkeypatch.setattr(Markdown, "update", update)
    async with app.run_test(size=(100, 30)) as pilot:
        app.copy_to_clipboard("old clipboard")
        app.get_chat_log().add_message(full_text, MessageType.ASSISTANT)
        await asyncio.wait_for(started.wait(), 2)
        await pilot.pause()
        markdown = app.get_chat_log().query_one(".msg-assistant", Markdown)
        block = markdown.query_one("MarkdownParagraph")
        await pilot.mouse_down(block)
        await pilot.hover(block, offset=(6, 0))
        await pilot.mouse_up(block, offset=(6, 0))
        assert app.clipboard == "old clipboard"
        release.set()
        await asyncio.wait_for(app.workers.wait_for_complete(), 5)
        assert markdown.source == full_text
        block = markdown.query_one("MarkdownParagraph")
        await pilot.mouse_down(block)
        await pilot.hover(block, offset=(6, 0))
        await pilot.mouse_up(block, offset=(6, 0))
        await pilot.pause()
        assert app.clipboard == app.screen.get_selected_text()
        assert app.clipboard.startswith("Select")
