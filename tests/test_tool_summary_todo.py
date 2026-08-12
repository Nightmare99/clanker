"""Tests for the todo checklist rendering added to clanker.ui.tool_summary."""

import json

from clanker.ui.tool_summary import build_todo_checklist_text, compact_result_summary


class TestBuildTodoChecklistText:
    def test_empty_list_returns_none(self) -> None:
        assert build_todo_checklist_text([]) is None

    def test_renders_header_and_items(self) -> None:
        todos = [
            {"content": "Read the config", "status": "completed", "active_form": "Read the config"},
            {"content": "Fix the bug", "status": "in_progress", "active_form": "Fixing the bug"},
            {"content": "Write tests", "status": "pending", "active_form": "Write tests"},
        ]
        text = build_todo_checklist_text(todos)
        plain = text.plain

        assert "1/3 done" in plain
        assert "✓" in plain
        assert "Read the config" in plain
        assert "▶" in plain
        assert "Fixing the bug" in plain  # active_form shown while in_progress
        assert "☐" in plain
        assert "Write tests" in plain

    def test_max_items_truncates_with_overflow_line(self) -> None:
        todos = [{"content": f"item {i}", "status": "pending"} for i in range(5)]
        text = build_todo_checklist_text(todos, max_items=2)
        plain = text.plain

        assert "item 0" in plain
        assert "item 1" in plain
        assert "item 2" not in plain
        assert "+3 more" in plain

    def test_no_max_items_shows_everything(self) -> None:
        todos = [{"content": f"item {i}", "status": "pending"} for i in range(5)]
        text = build_todo_checklist_text(todos)
        plain = text.plain

        for i in range(5):
            assert f"item {i}" in plain
        assert "more" not in plain


class TestCompactResultSummaryTodo:
    def test_todo_write_summary_counts(self) -> None:
        result = json.dumps({
            "ok": True,
            "todos": [{"content": "A", "status": "completed", "active_form": "A"}],
            "summary": {"total": 1, "completed": 1, "in_progress": 0, "pending": 0},
        })
        summary = compact_result_summary(result, "todo_write", None)
        assert summary == "1/1 done"

    def test_todo_write_no_todos_yet(self) -> None:
        result = json.dumps({
            "ok": True, "todos": [],
            "summary": {"total": 0, "completed": 0, "in_progress": 0, "pending": 0},
        })
        summary = compact_result_summary(result, "todo_write", None)
        assert summary == "no todos yet"

    def test_todo_write_error(self) -> None:
        result = json.dumps({"ok": False, "error": "todo #1 is missing 'content'"})
        summary = compact_result_summary(result, "todo_write", None)
        assert "missing" in summary
