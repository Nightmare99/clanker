"""Todo list tool for the Clanker agent.

Lets the agent write out a short plan as a checklist and update it as it
works through a task, so multi-step or ambiguous work stays visible and
trackable instead of disappearing into the agent's reasoning. Purely an
in-memory scratchpad for the current task -- not persistent storage (see
``remember``/``recall`` in memory_tools.py for that).

Uses thread-local storage, same as ``ask_tools.py``'s callback registry:
subagents run on their own dedicated thread (see subagent.py), so this keeps
each subagent's plan isolated from the parent session's rather than the two
clobbering each other through a shared list.
"""

from __future__ import annotations

import threading

from langchain_core.tools import tool

_VALID_STATUSES = ("pending", "in_progress", "completed")

_thread_locals = threading.local()


class TodoItem:
    """A single checklist entry."""

    __slots__ = ("content", "status", "active_form")

    def __init__(self, content: str, status: str = "pending", active_form: str = "") -> None:
        self.content = content
        self.status = status
        self.active_form = active_form

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "status": self.status,
            "active_form": self.active_form or self.content,
        }


class TodoStore:
    """Holds the current todo list for one thread (one session or subagent)."""

    def __init__(self) -> None:
        self._items: list[TodoItem] = []

    def write(self, items: list[TodoItem]) -> list[TodoItem]:
        self._items = items
        return list(self._items)

    def read(self) -> list[TodoItem]:
        return list(self._items)

    def clear(self) -> None:
        self._items = []


def get_todo_store() -> TodoStore:
    """Return the current thread's todo store, creating it on first use."""
    store = getattr(_thread_locals, "todo_store", None)
    if store is None:
        store = TodoStore()
        _thread_locals.todo_store = store
    return store


def _summary(items: list[TodoItem]) -> dict:
    return {
        "total": len(items),
        "completed": sum(1 for i in items if i.status == "completed"),
        "in_progress": sum(1 for i in items if i.status == "in_progress"),
        "pending": sum(1 for i in items if i.status == "pending"),
    }


@tool
def todo_write(todos: list[dict]) -> dict:
    """Write out (or update) the current task's todo list / plan.

    Optional planning tool -- use it for multi-step or non-trivial work
    (roughly 4+ distinct steps, or anything where the user benefits from
    seeing live progress). Skip it for trivial one- or two-step tasks; don't
    let list-management become busywork.

    Call this with the FULL list every time -- it always REPLACES the
    previous list, it does not append to it. To check an item off, resend
    the whole list with that item's status changed to "completed". Keep
    exactly one item "in_progress" at a time so it's clear what you're doing
    right now, and mark items "completed" as soon as they're actually done
    (not batched at the end).

    Args:
        todos: The complete current list of todo items, each a dict with:
            - content (str, required): imperative-form description, e.g.
              "Fix the login redirect bug".
            - status (str, required): one of "pending", "in_progress",
              "completed".
            - active_form (str, optional): present-continuous form shown
              while status is "in_progress", e.g. "Fixing the login
              redirect bug". Falls back to `content` if omitted.

    Returns:
        A dict with `ok`, the normalized `todos` list, and a `summary` of
        counts by status.
    """
    if not isinstance(todos, list):
        return {"ok": False, "error": "todos must be a list"}

    items: list[TodoItem] = []
    for i, raw in enumerate(todos):
        if not isinstance(raw, dict):
            return {"ok": False, "error": f"todo #{i + 1} must be an object"}
        content = str(raw.get("content", "")).strip()
        if not content:
            return {"ok": False, "error": f"todo #{i + 1} is missing 'content'"}
        status = str(raw.get("status", "pending")).strip().lower()
        if status not in _VALID_STATUSES:
            return {
                "ok": False,
                "error": (
                    f"todo #{i + 1} has invalid status '{status}' "
                    f"(must be one of: {', '.join(_VALID_STATUSES)})"
                ),
            }
        active_form = str(raw.get("active_form", "") or "").strip()
        items.append(TodoItem(content=content, status=status, active_form=active_form))

    saved = get_todo_store().write(items)

    return {
        "ok": True,
        "todos": [t.to_dict() for t in saved],
        "summary": _summary(saved),
    }


@tool
def todo_read() -> dict:
    """Read the current todo list / plan.

    Use this to check progress -- e.g. after a long detour, several tool
    calls without an update, or a context summarization -- before deciding
    what to work on next.

    Returns:
        A dict with `ok`, the current `todos` list, and a `summary` of
        counts by status. `todos` is empty if nothing has been written yet.
    """
    items = get_todo_store().read()
    return {
        "ok": True,
        "todos": [t.to_dict() for t in items],
        "summary": _summary(items),
    }
