"""Tests for the F3 conversation-history popup's rendering logic."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from rich.markdown import Markdown
from rich.rule import Rule
from rich.text import Text

from clanker.ui.history_modal import HistoryScreen


def _make_screen(messages) -> HistoryScreen:
    screen = HistoryScreen.__new__(HistoryScreen)
    screen._messages = messages
    return screen


def test_empty_history_shows_friendly_placeholder() -> None:
    screen = _make_screen([])
    body = screen._render_body()

    assert isinstance(body, Text)
    assert "No conversation history yet" in body.plain


def test_header_counts_only_human_and_ai_turns_with_content() -> None:
    messages = [
        HumanMessage(content="hi"),
        AIMessage(content="hello there"),
        SystemMessage(content="ignored -- not a conversational turn"),
        HumanMessage(content="   "),  # blank, should not count
    ]
    screen = _make_screen(messages)

    header = screen._render_header()

    assert "2 messages" in header.plain


def test_body_alternates_user_and_assistant_with_rule_between_exchanges() -> None:
    messages = [
        HumanMessage(content="first question"),
        AIMessage(content="first answer"),
        HumanMessage(content="second question"),
        AIMessage(content="second answer"),
    ]
    screen = _make_screen(messages)

    body = screen._render_body()
    parts = body.renderables

    # You / content / blank, then Rule before the second exchange's You header.
    labels = [p.plain for p in parts if isinstance(p, Text) and p.plain in ("❯ You", "◆ Clanker")]
    assert labels == ["❯ You", "◆ Clanker", "❯ You", "◆ Clanker"]

    rules = [p for p in parts if isinstance(p, Rule)]
    assert len(rules) == 1  # only between the two exchanges, not before the first turn

    markdowns = [p for p in parts if isinstance(p, Markdown)]
    assert len(markdowns) == 2  # assistant content rendered as markdown


def test_content_text_present_for_each_turn() -> None:
    messages = [HumanMessage(content="what's the capital of France?")]
    screen = _make_screen(messages)

    body = screen._render_body()
    texts = [p.plain for p in body.renderables if isinstance(p, Text)]

    assert "what's the capital of France?" in texts
