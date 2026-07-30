"""Tests for the typewriter reveal animation on assistant messages."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from clanker.ui.chat_log import ChatLog


@pytest.mark.asyncio
async def test_reveal_markdown_streams_in_growing_chunks() -> None:
    """_reveal_markdown calls widget.update() repeatedly with a growing prefix."""
    chat_log = ChatLog.__new__(ChatLog)
    chat_log._scroll_to_bottom = MagicMock()

    widget = MagicMock()
    widget.update = AsyncMock()

    text = "Hello there, this is a longer assistant response for the reveal test."

    await chat_log._reveal_markdown(widget, text)

    calls = [c.args[0] for c in widget.update.call_args_list]

    assert len(calls) > 1, "should reveal across multiple ticks, not in one shot"
    assert all(text.startswith(c) for c in calls), "each tick must be a prefix of the full text"
    assert all(len(calls[i]) < len(calls[i + 1]) for i in range(len(calls) - 1)), (
        "revealed length must strictly increase each tick"
    )
    assert calls[-1] == text, "final tick must show the complete text"


@pytest.mark.asyncio
async def test_reveal_markdown_empty_text_is_noop() -> None:
    """No ticks for empty content."""
    chat_log = ChatLog.__new__(ChatLog)
    chat_log._scroll_to_bottom = MagicMock()

    widget = MagicMock()
    widget.update = AsyncMock()

    await chat_log._reveal_markdown(widget, "")

    widget.update.assert_not_called()


@pytest.mark.asyncio
async def test_reveal_markdown_short_text_still_reaches_full_text() -> None:
    """A very short message still ends up fully revealed."""
    chat_log = ChatLog.__new__(ChatLog)
    chat_log._scroll_to_bottom = MagicMock()

    widget = MagicMock()
    widget.update = AsyncMock()

    await chat_log._reveal_markdown(widget, "ok")

    calls = [c.args[0] for c in widget.update.call_args_list]
    assert calls[-1] == "ok"
