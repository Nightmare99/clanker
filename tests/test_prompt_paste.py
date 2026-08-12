"""Tests for multi-line paste handling in the TUI's prompt input.

Regression 1: Textual's built-in Input._on_paste keeps only
``event.text.splitlines()[0]`` -- pasting multiple lines silently dropped
everything after the first. Fixed by collapsing multi-line pastes to a
"[pasted N lines]" placeholder in the visible (single-line) field, and
swapping the real text back in at submission time.

Regression 2: Textual dispatches same-named handlers across the *entire*
class MRO, not just the most-derived override -- so without
``event.prevent_default()``, ``Input``'s own ``_on_paste`` ran a second time
right after ours, re-inserting its first-line-only text after the
placeholder. These tests dispatch through ``post_message`` + a pilot pause
(the real Textual message-pump path), not by calling ``_on_paste`` directly,
specifically so they exercise that MRO-dispatch behavior.

Regression 3: terminals vary in what they actually send for line breaks in
a bracketed paste (observed: bare "\r" instead of "\n"), and Rich's Text --
which renders the expanded message in the chat log -- only treats "\n" as a
line break. Storing the pasted text verbatim carried whatever separator the
terminal used straight through to the chat log, where a "\r"-separated
paste rendered squashed onto one visual line. Fixed by normalizing to "\n"
when the paste is captured.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from textual import events
from textual.app import App, ComposeResult

from clanker.ui.app import ClankerApp, PromptInput


class _PromptHostApp(App):
    def compose(self) -> ComposeResult:
        yield PromptInput(id="prompt-input")


async def _paste(prompt: PromptInput, pilot, text: str) -> None:
    """Dispatch a paste through Textual's real message pump, not a direct call."""
    prompt.post_message(events.Paste(text))
    await pilot.pause()


async def test_multiline_paste_shows_placeholder_not_first_line_only() -> None:
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        await _paste(prompt, pilot, "def foo():\n    return 1\n\nprint(foo())")

        assert prompt.value == "[pasted 4 lines]"
        assert "def foo()" not in prompt.value


async def test_multiline_paste_does_not_also_append_first_line() -> None:
    """Regression: Input's base _on_paste must not ALSO fire and tack the
    first line on after the placeholder."""
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        await _paste(prompt, pilot, "alpha\nbeta\ngamma")

        assert prompt.value == "[pasted 3 lines]"
        assert not prompt.value.endswith("alpha")


async def test_singleline_paste_is_inserted_verbatim_exactly_once() -> None:
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        await _paste(prompt, pilot, "just one line")

        assert prompt.value == "just one line"


async def test_carriage_return_line_endings_are_normalized_to_newline() -> None:
    """Some terminals send bare "\\r" for line breaks in a bracketed paste --
    Rich's Text only recognizes "\\n", so a "\\r"-separated paste must be
    normalized or it renders squashed onto one visual line."""
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        await _paste(prompt, pilot, "def foo():\r    return 1\r\rprint(foo())")

        assert prompt.value == "[pasted 4 lines]"
        expanded, images = prompt.pop_expanded_value()
        assert expanded == "def foo():\n    return 1\n\nprint(foo())"
        assert "\r" not in expanded
        assert images == []


async def test_pop_expanded_value_swaps_placeholder_for_full_text() -> None:
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        pasted = "line one\nline two\nline three"
        await _paste(prompt, pilot, pasted)
        assert prompt.value == "[pasted 3 lines]"

        expanded, images = prompt.pop_expanded_value()

        assert expanded == pasted
        assert images == []
        assert prompt._pending_pastes == []


async def test_pop_expanded_value_preserves_surrounding_typed_text() -> None:
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        prompt.insert_text_at_cursor("please review:\n")
        await _paste(prompt, pilot, "a\nb\nc")
        prompt.insert_text_at_cursor(" -- thanks")

        assert prompt.value == "please review:\n[pasted 3 lines] -- thanks"

        expanded, images = prompt.pop_expanded_value()

        assert expanded == "please review:\na\nb\nc -- thanks"
        assert images == []


async def test_multiple_pastes_each_get_own_placeholder_and_expand_in_order() -> None:
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        await _paste(prompt, pilot, "x\ny")
        prompt.insert_text_at_cursor(" and ")
        await _paste(prompt, pilot, "p\nq")

        assert prompt.value == "[pasted 2 lines] and [pasted 2 lines]"

        expanded, images = prompt.pop_expanded_value()

        assert expanded == "x\ny and p\nq"
        assert images == []


async def test_escape_clears_pending_pastes() -> None:
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        await _paste(prompt, pilot, "a\nb")
        assert prompt._pending_pastes

        await pilot.press("escape")

        assert prompt.value == ""
        assert prompt._pending_pastes == []
        assert prompt._pending_images == []


async def test_empty_paste_is_noop() -> None:
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()

        await _paste(prompt, pilot, "")

        assert prompt.value == ""
        assert prompt._pending_pastes == []


async def test_submit_sends_expanded_text_but_histories_the_placeholder() -> None:
    """End-to-end through ClankerApp.on_input_submitted: the agent/chat log
    must see the real pasted text, while input history/recall keeps the safe
    single-line placeholder form."""
    app = _PromptHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.focus()
        prompt.insert_text_at_cursor("please review:\n")
        await _paste(prompt, pilot, "a\nb\nc")
        prompt.insert_text_at_cursor(" thanks")
        assert prompt.value == "please review:\n[pasted 3 lines] thanks"

        clanker_app = ClankerApp.__new__(ClankerApp)
        clanker_app._processing = False
        clanker_app._set_processing = MagicMock()
        clanker_app._handle_slash_command = MagicMock(return_value=None)  # not a slash command
        clanker_app._run_agent = MagicMock(return_value=None)  # avoid an unawaited coroutine
        clanker_app.run_worker = MagicMock()

        chat_log = MagicMock()
        clanker_app.get_prompt_input = lambda: prompt
        clanker_app.get_chat_log = lambda: chat_log

        clanker_app.on_input_submitted(SimpleNamespace(stop=lambda: None))

        chat_log.add_message.assert_called_once()
        sent_text = chat_log.add_message.call_args[0][0]
        assert sent_text == "please review:\na\nb\nc thanks"

        assert prompt._history[-1] == "please review:\n[pasted 3 lines] thanks"
        assert prompt.value == ""
        assert prompt._pending_pastes == []
