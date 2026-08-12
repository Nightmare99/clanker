"""Tests for the pinned TodoPanel widget (checklist docked above the input bar)."""

from __future__ import annotations

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
