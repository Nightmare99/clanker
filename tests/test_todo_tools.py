"""Tests for the todo_write/todo_read planning tools."""

import threading

from clanker.tools.todo_tools import (
    clear_todos_if_completed,
    format_current_todos_for_context,
    get_todo_store,
    todo_read,
    todo_write,
)


class TestTodoWrite:
    def setup_method(self) -> None:
        get_todo_store().clear()

    def test_write_returns_normalized_todos_and_summary(self) -> None:
        result = todo_write.invoke({
            "todos": [
                {"content": "Read the config", "status": "completed"},
                {"content": "Fix the bug", "status": "in_progress", "active_form": "Fixing the bug"},
                {"content": "Write tests", "status": "pending"},
            ]
        })

        assert result["ok"] is True
        assert result["summary"] == {
            "total": 3, "completed": 1, "in_progress": 1, "pending": 1,
        }
        assert result["todos"][0] == {
            "content": "Read the config", "status": "completed", "active_form": "Read the config",
        }
        assert result["todos"][1]["active_form"] == "Fixing the bug"

    def test_write_replaces_previous_list_wholesale(self) -> None:
        todo_write.invoke({"todos": [{"content": "A", "status": "pending"}]})
        result = todo_write.invoke({"todos": [{"content": "B", "status": "pending"}]})

        assert result["summary"]["total"] == 1
        assert result["todos"][0]["content"] == "B"

    def test_write_empty_list_clears(self) -> None:
        todo_write.invoke({"todos": [{"content": "A", "status": "pending"}]})
        result = todo_write.invoke({"todos": []})

        assert result["ok"] is True
        assert result["todos"] == []
        assert result["summary"]["total"] == 0

    def test_status_case_insensitive(self) -> None:
        result = todo_write.invoke({"todos": [{"content": "A", "status": "In_Progress"}]})
        assert result["todos"][0]["status"] == "in_progress"

    def test_active_form_falls_back_to_content(self) -> None:
        result = todo_write.invoke({"todos": [{"content": "Fix it", "status": "pending"}]})
        assert result["todos"][0]["active_form"] == "Fix it"

    def test_context_snapshot_preserves_exact_live_plan(self) -> None:
        todo_write.invoke({
            "todos": [
                {"content": "Inspect code", "status": "completed"},
                {"content": "Fix compaction", "status": "in_progress"},
            ]
        })

        context = format_current_todos_for_context()

        assert "[completed] Inspect code" in context
        assert "[in_progress] Fix compaction" in context
        assert "todo_write(todos=[])" in context

    def test_completed_plan_is_cleared_at_turn_boundary(self) -> None:
        todo_write.invoke({
            "todos": [
                {"content": "Patch", "status": "completed"},
                {"content": "Test", "status": "completed"},
            ]
        })

        assert clear_todos_if_completed() is True
        assert todo_read.invoke({})["todos"] == []

    def test_incomplete_plan_survives_turn_boundary(self) -> None:
        todo_write.invoke({
            "todos": [
                {"content": "Patch", "status": "completed"},
                {"content": "Test", "status": "pending"},
            ]
        })

        assert clear_todos_if_completed() is False
        assert todo_read.invoke({})["summary"]["total"] == 2

    def test_rejects_non_list(self) -> None:
        # Bypasses the args_schema (which already rejects this at the
        # langchain layer) to exercise the function's own defense-in-depth
        # check, same as ask_user's -- see ask_tools.py.
        result = todo_write.func(todos="not a list")
        assert result["ok"] is False
        assert "list" in result["error"]

    def test_rejects_non_dict_item(self) -> None:
        result = todo_write.func(todos=["just a string"])
        assert result["ok"] is False
        assert "object" in result["error"]

    def test_rejects_missing_content(self) -> None:
        result = todo_write.invoke({"todos": [{"status": "pending"}]})
        assert result["ok"] is False
        assert "content" in result["error"]

    def test_rejects_invalid_status(self) -> None:
        result = todo_write.invoke({"todos": [{"content": "A", "status": "done"}]})
        assert result["ok"] is False
        assert "status" in result["error"]

    def test_a_rejected_write_does_not_clobber_existing_list(self) -> None:
        todo_write.invoke({"todos": [{"content": "A", "status": "pending"}]})
        bad = todo_write.invoke({"todos": [{"content": "B", "status": "bogus"}]})
        assert bad["ok"] is False

        current = todo_read.invoke({})
        assert current["todos"][0]["content"] == "A"


class TestTodoRead:
    def setup_method(self) -> None:
        get_todo_store().clear()

    def test_read_empty_initially(self) -> None:
        result = todo_read.invoke({})
        assert result["ok"] is True
        assert result["todos"] == []
        assert result["summary"]["total"] == 0

    def test_read_reflects_last_write(self) -> None:
        todo_write.invoke({"todos": [{"content": "A", "status": "completed"}]})
        result = todo_read.invoke({})
        assert result["todos"][0]["content"] == "A"
        assert result["summary"]["completed"] == 1


class TestTodoStoreThreadIsolation:
    """Subagents run on their own thread (see subagent.py) and must not
    clobber the parent session's plan -- get_todo_store() is thread-local."""

    def test_each_thread_gets_its_own_store(self) -> None:
        get_todo_store().clear()
        todo_write.invoke({"todos": [{"content": "main thread item", "status": "pending"}]})

        other_thread_result = {}

        def worker() -> None:
            other_thread_result["before_write"] = todo_read.invoke({})["todos"]
            todo_write.invoke({"todos": [{"content": "worker item", "status": "pending"}]})
            other_thread_result["after_write"] = todo_read.invoke({})["todos"]

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        # The worker thread started with an empty list of its own...
        assert other_thread_result["before_write"] == []
        # ...and its write didn't touch the main thread's list.
        assert other_thread_result["after_write"][0]["content"] == "worker item"
        main_thread_todos = todo_read.invoke({})["todos"]
        assert main_thread_todos[0]["content"] == "main thread item"
