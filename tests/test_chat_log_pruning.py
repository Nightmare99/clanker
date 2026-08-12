"""Tests for ChatLog history pruning (long-session performance)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from clanker.ui.chat_log import ChatLog, ToolEntry


@pytest.fixture
def make_chat_log(monkeypatch):
    """Factory for a ChatLog with just enough state for _maybe_prune, no live Textual app."""

    def _make(max_widgets: int) -> ChatLog:
        chat_log = ChatLog.__new__(ChatLog)
        chat_log._messages = []
        chat_log._tool_entries = {}
        chat_log._hero_widget = None
        chat_log._hero_rule = None
        chat_log._prune_placeholder = None
        chat_log._pruned_count = 0
        chat_log.mount = MagicMock()

        settings = MagicMock()
        settings.output.chat_log_max_widgets = max_widgets
        monkeypatch.setattr("clanker.config.get_settings", lambda: settings)

        # The placeholder Static needs a running Textual App to render for
        # real; these tests only care about _maybe_prune's bookkeeping, so
        # swap in a plain mock rather than standing up a full App.
        monkeypatch.setattr(
            "clanker.ui.chat_log.Static", MagicMock(side_effect=lambda *a, **k: MagicMock())
        )

        return chat_log

    return _make


def _widgets(n: int) -> list[MagicMock]:
    return [MagicMock() for _ in range(n)]


def test_no_prune_below_batch_threshold(make_chat_log) -> None:
    """A small overshoot doesn't trigger pruning -- avoids remove+relayout churn."""
    chat_log = make_chat_log(max_widgets=100)
    chat_log._messages = _widgets(105)  # only 5 over the limit, batch threshold is 20

    chat_log._maybe_prune()

    assert len(chat_log._messages) == 105
    assert chat_log._pruned_count == 0


def test_prune_removes_oldest_widgets_over_limit(make_chat_log) -> None:
    chat_log = make_chat_log(max_widgets=100)
    widgets = _widgets(150)
    chat_log._messages = list(widgets)

    chat_log._maybe_prune()

    # Oldest widgets were unmounted.
    for w in widgets[:50]:
        w.remove.assert_called_once()
    for w in widgets[50:]:
        w.remove.assert_not_called()

    assert chat_log._pruned_count == 50
    # A placeholder was inserted in place of the removed history.
    assert chat_log._prune_placeholder is not None
    assert len(chat_log._messages) == 150 - 50 + 1


def test_prune_never_removes_running_tool_widgets(make_chat_log) -> None:
    chat_log = make_chat_log(max_widgets=100)
    widgets = _widgets(150)
    chat_log._messages = list(widgets)

    # The oldest widget belongs to a tool call that's still running.
    running_entry = ToolEntry(
        tool_name="execute_shell", args="", status="running", header_widget=widgets[0]
    )
    chat_log._tool_entries["tool:1"] = running_entry

    chat_log._maybe_prune()

    widgets[0].remove.assert_not_called()
    assert widgets[0] in chat_log._messages


def test_prune_protects_hero_and_placeholder(make_chat_log) -> None:
    chat_log = make_chat_log(max_widgets=100)
    hero_widget = MagicMock()
    hero_rule = MagicMock()
    chat_log._hero_widget = hero_widget
    chat_log._hero_rule = hero_rule
    chat_log._messages = [hero_widget, hero_rule, *_widgets(150)]

    chat_log._maybe_prune()

    hero_widget.remove.assert_not_called()
    hero_rule.remove.assert_not_called()
    assert hero_widget in chat_log._messages
    assert hero_rule in chat_log._messages


def test_prune_reuses_single_placeholder_across_batches(make_chat_log) -> None:
    chat_log = make_chat_log(max_widgets=100)
    chat_log._messages = _widgets(150)
    chat_log._maybe_prune()
    placeholder = chat_log._prune_placeholder
    first_pruned_count = chat_log._pruned_count
    assert placeholder is not None

    # Grow well past the limit again and prune a second time.
    chat_log._messages.extend(_widgets(100))
    chat_log._maybe_prune()

    assert chat_log._prune_placeholder is placeholder
    assert chat_log._pruned_count > first_pruned_count
    placeholder.update.assert_called()


def test_stale_finalized_tool_entries_are_dropped(make_chat_log) -> None:
    chat_log = make_chat_log(max_widgets=100)
    widgets = _widgets(150)
    chat_log._messages = list(widgets)

    finished_entry = ToolEntry(
        tool_name="read_file", args="", status="success", header_widget=widgets[0]
    )
    chat_log._tool_entries["tool:1"] = finished_entry

    chat_log._maybe_prune()

    assert "tool:1" not in chat_log._tool_entries
