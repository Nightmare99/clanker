"""Tests for atomic (whole-block) deletion of paste/image placeholders.

Regression: "[pasted N lines]"/"[Image #N]" tokens were plain text as far as
Input was concerned, so Backspace/Delete ate into them one character at a
time -- corrupting the placeholder so it no longer matched what
pop_expanded_value() looked for, silently leaving mangled text in the sent
message instead of either keeping or fully removing the paste. Fixed by
overriding action_delete_left/action_delete_right to remove a whole
overlapping placeholder (and forget the paste/image it stood for) in one
keystroke.

Tests dispatch through pilot.press(...) (real key -> binding -> action
resolution), not by calling the action methods directly, since that's the
only way action_delete_left/right actually get exercised by a keypress.
"""

from __future__ import annotations

from textual import events
from textual.app import App, ComposeResult

from clanker.ui.app import PromptInput
from clanker.ui.clipboard_image import ClipboardImage


class _PromptHostApp(App):
    def compose(self) -> ComposeResult:
        yield PromptInput(id="prompt-input")


async def _paste(prompt: PromptInput, pilot, text: str) -> None:
    prompt.post_message(events.Paste(text))
    await pilot.pause()


async def test_backspace_right_after_placeholder_removes_whole_block() -> None:
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        await _paste(prompt, pilot, "a\nb\nc")
        assert prompt.value == "[pasted 3 lines]"

        await pilot.press("backspace")

        assert prompt.value == ""
        assert prompt._pending_pastes == []


async def test_delete_right_before_placeholder_removes_whole_block() -> None:
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        await _paste(prompt, pilot, "a\nb\nc")
        prompt.cursor_position = 0  # move to the start, i.e. right before it

        await pilot.press("delete")

        assert prompt.value == ""
        assert prompt._pending_pastes == []


async def test_backspace_mid_placeholder_removes_whole_block() -> None:
    """Cursor moved (e.g. via arrow keys) into the middle of the token."""
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        await _paste(prompt, pilot, "a\nb\nc")
        assert prompt.value == "[pasted 3 lines]"
        prompt.cursor_position = len(prompt.value) // 2  # somewhere in the middle

        await pilot.press("backspace")

        assert prompt.value == ""
        assert prompt._pending_pastes == []


async def test_backspace_preserves_surrounding_typed_text() -> None:
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        prompt.insert_text_at_cursor("before ")
        await _paste(prompt, pilot, "a\nb")
        prompt.insert_text_at_cursor(" after")
        assert prompt.value == "before [pasted 2 lines] after"

        # Cursor is right after " after"; move it to right after the placeholder.
        prompt.cursor_position = len("before [pasted 2 lines]")
        await pilot.press("backspace")

        assert prompt.value == "before  after"
        assert prompt._pending_pastes == []


async def test_normal_backspace_still_deletes_one_character() -> None:
    """Regression guard: ordinary typed text must still delete char-by-char."""
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        prompt.insert_text_at_cursor("hello")
        await pilot.press("backspace")

        assert prompt.value == "hell"


async def test_duplicate_placeholders_delete_independently() -> None:
    """Two identical-looking placeholders must map back to their own pasted
    content -- deleting one must not disturb the other's expansion."""
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        await _paste(prompt, pilot, "x\ny")
        prompt.insert_text_at_cursor(" and ")
        await _paste(prompt, pilot, "p\nq")
        assert prompt.value == "[pasted 2 lines] and [pasted 2 lines]"

        # Delete the SECOND occurrence (cursor is already right after it).
        await pilot.press("backspace")

        assert prompt.value == "[pasted 2 lines] and "
        expanded, images = prompt.pop_expanded_value()
        assert expanded == "x\ny and "
        assert images == []


async def test_backspace_removes_whole_image_placeholder() -> None:
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        prompt._image_counter = 1
        placeholder = "[Image #1]"
        prompt._pending_images.append((placeholder, ClipboardImage(data=b"fake", mime_type="image/png")))
        prompt.insert_text_at_cursor(placeholder)
        assert prompt.value == placeholder

        await pilot.press("backspace")

        assert prompt.value == ""
        assert prompt._pending_images == []


async def test_delete_removes_whole_image_placeholder_from_middle() -> None:
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        placeholder = "[Image #1]"
        prompt._image_counter = 1
        prompt._pending_images.append((placeholder, ClipboardImage(data=b"fake", mime_type="image/png")))
        prompt.insert_text_at_cursor(f"see {placeholder} please")
        prompt.cursor_position = len("see [Ima")  # inside the token

        await pilot.press("delete")

        assert prompt.value == "see  please"
        assert prompt._pending_images == []
