"""Command shortcuts use editor actions without changing terminal controls."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from textual.widgets import Input, Markdown, Static, TextArea

from clanker.ui import keyboard
from clanker.ui.app import ClankerApp
from clanker.ui.clipboard_image import ClipboardImage
from clanker.ui.console import Console


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(ClankerApp, "_load_history", lambda self: [])
    monkeypatch.setattr(ClankerApp, "_save_history", lambda self: None)
    application = ClankerApp(Console())
    application._play_hero = AsyncMock()
    return application


@pytest.mark.parametrize("composer", [False, True])
async def test_command_editing_in_focused_input(app, composer, monkeypatch):
    monkeypatch.setattr("clanker.ui.message_composer.read_clipboard_image", lambda: None)
    app.action_interrupt = MagicMock()
    async with app.run_test(size=(100, 30)) as pilot:
        app.get_prompt_input().value = "Keep this text"
        if composer:
            await pilot.press("f5")
        editor = app.screen.query_one(TextArea) if composer else app.get_prompt_input()
        await pilot.press("super+a", "super+c")
        assert editor.selected_text == "Keep this text"
        assert app.clipboard == "Keep this text"
        await pilot.press("super+x")
        assert (editor.text if composer else editor.value) == ""
        assert app.clipboard == "Keep this text"
        await pilot.press("super+v")
        await app.workers.wait_for_complete()
        assert (editor.text if composer else editor.value) == "Keep this text"
        await pilot.press("super+c")  # No selection: never interrupt.
        app.action_interrupt.assert_not_called()
        if composer:
            await pilot.press("escape")


async def test_command_copy_screen_selection_and_control_interrupt(app):
    app.action_interrupt = MagicMock()
    async with app.run_test(size=(100, 30)) as pilot:
        markdown = Markdown("Copy this paragraph")
        await app.get_chat_log().mount(markdown)
        await pilot.pause()
        paragraph = markdown.query_one("MarkdownParagraph")
        await pilot.mouse_down(paragraph, offset=(0, 0))
        await pilot.hover(paragraph, offset=(8, 0))
        await pilot.mouse_up(paragraph, offset=(8, 0))
        selected = app.screen.get_selected_text()
        assert selected and "Copy this" in selected
        await pilot.press("super+c")
        assert app.clipboard == selected
        app.screen.clear_selection()
        app.get_prompt_input().focus()
        await pilot.press("super+c")
        app.action_interrupt.assert_not_called()
        await pilot.press("ctrl+c")
        app.action_interrupt.assert_called_once()


@pytest.mark.parametrize("composer", [False, True])
async def test_command_paste_keeps_image_handling(app, composer, monkeypatch):
    image = ClipboardImage(b"image data", "image/png")
    monkeypatch.setattr("clanker.ui.app.read_clipboard_image", lambda: image)
    monkeypatch.setattr("clanker.ui.message_composer.read_clipboard_image", lambda: image)
    async with app.run_test(size=(100, 30)) as pilot:
        if composer:
            await pilot.press("f5")
        await pilot.press("super+v")
        await app.workers.wait_for_complete()
        if composer:
            assert app.screen.query_one(TextArea).text == "[Image #1]"
            assert app.screen._images == [("[Image #1]", image)]
            await pilot.press("escape")
        else:
            assert app.get_prompt_input().value == "[Image #1]"
            assert app.get_prompt_input()._pending_images == [("[Image #1]", image)]


async def test_composer_command_undo_redo(app):
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("f5", "a", "b", "c")
        editor = app.screen.query_one(TextArea)
        assert editor.text == "abc"
        await pilot.press("super+z")
        assert editor.text == ""
        await pilot.press("shift+super+z")
        assert editor.text == "abc"
        await pilot.press("escape")


async def test_command_edit_shortcuts_work_in_other_modal_inputs(app):
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("f6")
        field = app.screen.query_one(Input)
        field.focus()
        field.value = "Search memory"
        await pilot.press("super+a", "super+c")
        assert app.clipboard == "Search memory"
        await pilot.press("escape")


@pytest.mark.parametrize("macos", [False, True])
@pytest.mark.parametrize("composer", [False, True])
async def test_control_copy_respects_platform_with_selected_input(app, monkeypatch, macos, composer):
    monkeypatch.setattr(keyboard, "is_macos", lambda: macos)
    app.action_interrupt = MagicMock()
    async with app.run_test(size=(100, 30)) as pilot:
        app.get_prompt_input().value = "Selected text"
        if composer:
            await pilot.press("f5")
        editor = app.focused
        editor.action_select_all()
        await pilot.pause()  # Finish copy-on-selection before testing Ctrl+C.
        app.copy_to_clipboard("original clipboard")
        # Copy-on-selection may still be queued on a busy CI runner. Assert
        # the key's action directly instead of racing that independent copy.
        copy_action = MagicMock(wraps=app._copy_selection)
        monkeypatch.setattr(app, "_copy_selection", copy_action)
        await pilot.press("ctrl+c")
        assert editor.selected_text == "Selected text"
        if macos:
            app.action_interrupt.assert_called_once()
            copy_action.assert_not_called()
            await pilot.press("super+c")
            copy_action.assert_called_once()
            assert app.clipboard == "Selected text"
        else:
            app.action_interrupt.assert_not_called()
            copy_action.assert_called_once()
            assert app.clipboard == "Selected text"
        if composer:
            await pilot.press("escape")


@pytest.mark.parametrize("composer", [False, True])
async def test_macos_disables_control_edit_aliases(app, monkeypatch, composer):
    monkeypatch.setattr(keyboard, "is_macos", lambda: True)
    paste_image = MagicMock(return_value=None)
    monkeypatch.setattr("clanker.ui.app.read_clipboard_image", paste_image)
    monkeypatch.setattr("clanker.ui.message_composer.read_clipboard_image", paste_image)
    async with app.run_test(size=(100, 30)) as pilot:
        app.get_prompt_input().value = "Original text"
        if composer:
            await pilot.press("f5")
        screen = app.screen
        editor = app.focused
        await pilot.press("end", "!")
        editor.action_select_all()
        await pilot.pause()
        selection = editor.selection
        app.copy_to_clipboard("clipboard text")
        await pilot.press(
            "ctrl+x", "ctrl+v", "ctrl+z", "ctrl+y",
            "ctrl+shift+z", "ctrl+shift+a", "ctrl+enter",
        )
        await app.workers.wait_for_complete()
        assert app.screen is screen
        assert (editor.text if composer else editor.value) == "Original text!"
        assert editor.selection == selection
        assert app.clipboard == "clipboard text"
        paste_image.assert_not_called()
        if composer:
            await pilot.press("super+z")
            assert editor.text == "Original text"
            await pilot.press("shift+super+z")
            assert editor.text == "Original text!"
            await pilot.press("escape")


@pytest.mark.parametrize("macos", [False, True])
async def test_native_composer_send_and_platform_help(app, monkeypatch, macos):
    monkeypatch.setattr(keyboard, "is_macos", lambda: macos)
    app._processing = True
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("f1")
        help_text = str(app.screen.query_one(Static).render())
        assert ("macOS editing shortcuts" in help_text) == macos
        assert keyboard.edit_label("Enter") in help_text
        await pilot.press("escape", "f5", "a")
        title = str(app.screen.query_one("#composer-title", Static).render())
        assert keyboard.edit_label("Enter") in title
        await pilot.press(keyboard.edit_key("enter"))
        assert app._input_queue.get_nowait() == "a"


async def test_other_platform_control_editing_is_preserved(app, monkeypatch):
    monkeypatch.setattr(keyboard, "is_macos", lambda: False)
    monkeypatch.setattr("clanker.ui.message_composer.read_clipboard_image", lambda: None)
    async with app.run_test(size=(100, 30)) as pilot:
        app.get_prompt_input().value = "Control edit"
        await pilot.press("ctrl+shift+a", "ctrl+x", "ctrl+v")
        assert app.get_prompt_input().value == "Control edit"
        await pilot.press("f5", "ctrl+z")
        editor = app.screen.query_one(TextArea)
        editor.action_select_all()
        await pilot.press("ctrl+x")
        assert editor.text == ""
        await pilot.press("ctrl+z")
        assert editor.text == "Control edit"
        await pilot.press("ctrl+y")
        assert editor.text == ""
        await pilot.press("ctrl+v")
        await app.workers.wait_for_complete()
        assert editor.text == "Control edit"
        await pilot.press("escape")


async def test_iterm_command_copy_sequence_reaches_native_clipboard(app, monkeypatch):
    from textual import events
    from textual._xterm_parser import XTermParser

    from clanker.ui import native_clipboard

    monkeypatch.setattr(keyboard, "is_macos", lambda: True)
    monkeypatch.setattr(native_clipboard, "is_local_macos", lambda: True)
    write = AsyncMock(return_value=True)
    monkeypatch.setattr(native_clipboard, "write_text", write)
    app.action_interrupt = MagicMock()
    async with app.run_test(size=(100, 30)) as pilot:
        # Enable the production clipboard branch, but mock the native writer.
        monkeypatch.setattr(type(app._driver), "is_headless", property(lambda self: False))
        prompt = app.get_prompt_input()
        prompt.value = "Copy to the real pasteboard"
        prompt.action_select_all()
        await pilot.pause()
        await app.workers.wait_for_complete()
        write.reset_mock()
        parsed = [event for event in XTermParser().feed("\x1b[99;9u") if isinstance(event, events.Key)]
        assert [event.key for event in parsed] == ["super+c"]
        app.post_message(parsed[0])
        await pilot.pause()
        await app.workers.wait_for_complete()
        write.assert_awaited_once_with("Copy to the real pasteboard")
        assert app.clipboard == "Copy to the real pasteboard"
        app.action_interrupt.assert_not_called()


async def test_headless_copy_does_not_change_system_clipboard(app, monkeypatch):
    from clanker.ui import native_clipboard

    monkeypatch.setattr(native_clipboard, "is_local_macos", lambda: True)
    write = AsyncMock()
    monkeypatch.setattr(native_clipboard, "write_text", write)
    async with app.run_test() as pilot:
        app.get_prompt_input().value = "Headless copy"
        await pilot.press("super+a", "super+c")
        assert app.clipboard == "Headless copy"
        write.assert_not_called()
