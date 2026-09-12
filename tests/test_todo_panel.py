"""Tests for the pinned TodoPanel widget (checklist docked above the input bar)."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from clanker.ui.app import TodoPanel


class _TodoHostApp(App):
    def compose(self) -> ComposeResult:
        yield TodoPanel(id="todo-panel")


async def test_panel_hidden_by_default() -> None:
    app = _TodoHostApp()
    async with app.run_test():
        panel = app.query_one(TodoPanel)
        assert panel.display is False


async def test_panel_shown_with_incomplete_items() -> None:
    app = _TodoHostApp()
    async with app.run_test():
        panel = app.query_one(TodoPanel)
        panel.set_todos([
            {"content": "Fix the bug", "status": "in_progress", "active_form": "Fixing the bug"},
            {"content": "Write tests", "status": "pending", "active_form": "Write tests"},
        ])

        assert panel.display is True
        plain = panel.content.plain
        assert "0/2 done" in plain
        assert "Fixing the bug" in plain  # active_form used while in_progress
        assert "Write tests" in plain


async def test_panel_hides_when_all_items_completed() -> None:
    app = _TodoHostApp()
    async with app.run_test():
        panel = app.query_one(TodoPanel)
        panel.set_todos([{"content": "A", "status": "pending"}])
        assert panel.display is True

        panel.set_todos([{"content": "A", "status": "completed", "active_form": "A"}])
        assert panel.display is False


async def test_panel_hides_on_empty_list() -> None:
    app = _TodoHostApp()
    async with app.run_test():
        panel = app.query_one(TodoPanel)
        panel.set_todos([{"content": "A", "status": "pending"}])
        assert panel.display is True

        panel.set_todos([])
        assert panel.display is False


async def test_panel_caps_visible_items_with_overflow_line() -> None:
    app = _TodoHostApp()
    async with app.run_test():
        panel = app.query_one(TodoPanel)
        todos = [
            {"content": f"item {i}", "status": "pending", "active_form": f"item {i}"}
            for i in range(TodoPanel.MAX_VISIBLE_ITEMS + 3)
        ]
        panel.set_todos(todos)

        plain = panel.content.plain
        assert "item 0" in plain
        assert "+3 more" in plain


@pytest.mark.parametrize("count,width", [(7, 100), (11, 50)])
async def test_actual_app_keeps_counted_rows_above_prompt(count, width) -> None:
    from clanker.ui.app import ClankerApp
    from clanker.ui.console import Console

    app = ClankerApp(Console())

    async def no_hero(*args):
        pass

    app._play_hero = no_hero
    async with app.run_test(size=(width, 30)) as pilot:
        panel = app.get_todo_panel()
        panel.set_todos([
            {"content": f"item {i} " + "long label " * 12,
             "status": "completed" if i < 4 else "pending"}
            for i in range(count)
        ])
        app.get_message_queue().add_pending("Queued follow-up")
        await pilot.pause()
        rows = [strip.text for strip in app.screen._compositor.render_strips()]
        screen = "\n".join(rows)
        assert f"4/{count} done" in screen
        for i in range(min(count, panel.MAX_VISIBLE_ITEMS)):
            assert f"item {i} " in screen
        if count > panel.MAX_VISIBLE_ITEMS:
            assert "+3 more" in screen
        assert "Queued follow-up" in screen
        assert panel.region.bottom <= app.query_one("#prompt-bar").region.y
        assert app.get_message_queue().region.bottom <= panel.region.y
        assert app.get_prompt_input().region.height == 1
