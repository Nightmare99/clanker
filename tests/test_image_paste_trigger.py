"""Tests for the PromptInput trigger paths that lead into an OS-clipboard
image check, and the resulting placeholder/pending-image bookkeeping.

Bracketed paste can't carry image bytes at all, so there are two distinct
"maybe there's an image" triggers, both covered here:
  1. `_on_paste` fires with empty text (the terminal forwarded a paste with
     nothing usable in it).
  2. Ctrl+V (`action_paste`) fires with Textual's own internal text
     clipboard empty -- either nothing was ever copied in-app, or the
     terminal swallowed Ctrl+V for its own paste and sent no Paste event at
     all because the OS clipboard held only an image.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from textual import events
from textual.app import App, ComposeResult

from clanker.ui.app import ClankerApp, PromptInput
from clanker.ui.clipboard_image import ClipboardImage


class _PromptHostApp(App):
    def compose(self) -> ComposeResult:
        yield PromptInput(id="prompt-input")


async def test_empty_paste_triggers_clipboard_image_check() -> None:
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()
        prompt._start_clipboard_image_check = MagicMock()

        prompt.post_message(events.Paste(""))
        await pilot.pause()

        prompt._start_clipboard_image_check.assert_called_once()


async def test_ctrl_v_with_empty_internal_clipboard_triggers_image_check() -> None:
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()
        assert app.clipboard == ""  # nothing copied in-app yet
        prompt._start_clipboard_image_check = MagicMock()

        await pilot.press("ctrl+v")

        prompt._start_clipboard_image_check.assert_called_once()


async def test_ctrl_v_with_nonempty_internal_clipboard_pastes_text_normally() -> None:
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()
        app.copy_to_clipboard("hello from app clipboard")
        prompt._start_clipboard_image_check = MagicMock()

        await pilot.press("ctrl+v")

        prompt._start_clipboard_image_check.assert_not_called()
        assert prompt.value == "hello from app clipboard"


async def test_try_paste_image_inserts_placeholder_and_stores_image() -> None:
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        fake_image = ClipboardImage(data=b"pngdata", mime_type="image/png")
        with patch("clanker.ui.app.read_clipboard_image", return_value=fake_image):
            await prompt._try_paste_image()

        assert prompt.value == "[Image #1]"
        assert len(prompt._pending_images) == 1
        placeholder, image = prompt._pending_images[0]
        assert placeholder == "[Image #1]"
        assert image is fake_image


async def test_multiple_images_get_sequential_placeholders() -> None:
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        image1 = ClipboardImage(data=b"one", mime_type="image/png")
        image2 = ClipboardImage(data=b"two", mime_type="image/png")

        with patch("clanker.ui.app.read_clipboard_image", return_value=image1):
            await prompt._try_paste_image()
        prompt.insert_text_at_cursor(" and ")
        with patch("clanker.ui.app.read_clipboard_image", return_value=image2):
            await prompt._try_paste_image()

        assert prompt.value == "[Image #1] and [Image #2]"


async def test_no_image_found_and_no_tool_warns_once() -> None:
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()
        prompt.notify = MagicMock()

        with patch("clanker.ui.app.read_clipboard_image", return_value=None), patch(
            "clanker.ui.app.clipboard_image_tool_available", return_value=False
        ):
            await prompt._try_paste_image()
            await prompt._try_paste_image()

        assert prompt.value == ""
        prompt.notify.assert_called_once()
        assert prompt._warned_no_clipboard_tool is True


async def test_no_image_found_but_tool_available_no_warning() -> None:
    """Genuinely empty clipboard (not a missing-tool problem) shouldn't nag."""
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()
        prompt.notify = MagicMock()

        with patch("clanker.ui.app.read_clipboard_image", return_value=None), patch(
            "clanker.ui.app.clipboard_image_tool_available", return_value=True
        ):
            await prompt._try_paste_image()

        prompt.notify.assert_not_called()


async def test_submit_builds_multimodal_message_with_pasted_image() -> None:
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()
        prompt.insert_text_at_cursor("what's in this screenshot? ")

        fake_image = ClipboardImage(data=b"screenshotbytes", mime_type="image/png")
        with patch("clanker.ui.app.read_clipboard_image", return_value=fake_image):
            await prompt._try_paste_image()
        assert prompt.value == "what's in this screenshot? [Image #1]"

        clanker_app = ClankerApp.__new__(ClankerApp)
        clanker_app._processing = False
        clanker_app._set_processing = MagicMock()
        clanker_app._handle_slash_command = MagicMock(return_value=None)
        clanker_app._run_agent = MagicMock(return_value=None)  # avoid an unawaited coroutine
        clanker_app.run_worker = MagicMock()

        chat_log = MagicMock()
        clanker_app.get_prompt_input = lambda: prompt
        clanker_app.get_chat_log = lambda: chat_log

        clanker_app.on_input_submitted(SimpleNamespace(stop=lambda: None))

        # _run_agent(text, images) was constructed via run_worker(self._run_agent(...)) --
        # run_worker is mocked, so assert on what it was called with.
        clanker_app.run_worker.assert_called_once()
        # _run_agent itself was called (as a coroutine function) to build the
        # awaitable passed to run_worker.
        clanker_app._run_agent.assert_called_once()
        call_text, call_images = clanker_app._run_agent.call_args[0]
        assert call_text == "what's in this screenshot? [Image #1]"
        assert call_images == [fake_image]

        assert prompt.value == ""
        assert prompt._pending_images == []


async def test_queued_followup_with_image_warns_and_drops_image() -> None:
    """The follow-up queue only carries plain text -- pasting an image while
    the agent is already processing must warn, not silently lose it without
    a trace."""
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        fake_image = ClipboardImage(data=b"x", mime_type="image/png")
        with patch("clanker.ui.app.read_clipboard_image", return_value=fake_image):
            await prompt._try_paste_image()
        prompt.insert_text_at_cursor(" follow up")

        clanker_app = ClankerApp.__new__(ClankerApp)
        clanker_app._processing = True  # agent is mid-turn
        import asyncio

        clanker_app._input_queue = asyncio.Queue()
        chat_log = MagicMock()
        message_queue = MagicMock()
        clanker_app.get_prompt_input = lambda: prompt
        clanker_app.get_chat_log = lambda: chat_log
        clanker_app.get_message_queue = lambda: message_queue

        clanker_app.on_input_submitted(SimpleNamespace(stop=lambda: None))

        # A warning was shown (some add_message call whose text mentions the limitation).
        warning_calls = [
            c for c in chat_log.add_message.call_args_list
            if "queued follow-up" in c.args[0]
        ]
        assert len(warning_calls) == 1

        # The queued text itself is still delivered (image just isn't attached).
        queued_text = clanker_app._input_queue.get_nowait()
        assert queued_text == "[Image #1] follow up"
