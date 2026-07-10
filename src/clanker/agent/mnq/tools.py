"""LangChain tools for interacting with the MNQ task board."""

import json
from typing import Any, List, Optional

from langchain_core.tools import tool

from clanker.agent.mnq.board import TaskBoard

# Thread/Process global for the active task board
_active_board: Optional[TaskBoard] = None


def set_active_board(board: TaskBoard) -> None:
    """Set the active task board for the tools.

    Args:
        board: TaskBoard instance.
    """
    global _active_board
    _active_board = board


def get_active_board() -> TaskBoard:
    """Get the active task board.

    Returns:
        TaskBoard instance.

    Raises:
        ValueError: If no active board is set.
    """
    if _active_board is None:
        raise ValueError("No active task board. MNQ mode is not initialized.")
    return _active_board


@tool
def view_task_board(
    filter_role: Optional[str] = None, status: Optional[str] = None
) -> str:
    """View the current state of the shared task board.

    You can optionally filter by role (e.g. 'backend', 'frontend', 'devops',
    'dba', 'tester') or status (e.g. 'pending', 'in_progress', 'complete',
    'verified').

    Args:
        filter_role: Optional assignee role to filter by.
        status: Optional status to filter by.

    Returns:
        JSON-formatted string representing the tasks on the board.
    """
    try:
        board = get_active_board()
        tasks = board.get_tasks(filter_role=filter_role, status=status)
        result = []
        for t in tasks:
            result.append({
                "id": t["id"],
                "title": t["title"],
                "type": t["type"],
                "assignee_role": t["assignee_role"],
                "status": t["status"],
                "priority": t["priority"],
                "depends_on": t["depends_on"],
                "description": t["description"],
                "context_refs": t["context_refs"],
                "acceptance_criteria": t["acceptance_criteria"],
                "result_summary": t["result_summary"],
                "diff_ref": t["diff_ref"],
                "defect_of": t["defect_of"],
                "needs_followup": t["needs_followup"],
                "followup_question": t["followup_question"],
                "followup_answer": t["followup_answer"],
            })
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error viewing task board: {e}"


@tool
def add_task(
    id: str,
    title: str,
    type: str,
    assignee_role: str,
    priority: str = "medium",
    depends_on: List[str] = [],
    description: str = "",
    context_refs: List[str] = [],
    acceptance_criteria: List[str] = [],
    defect_of: Optional[str] = None,
) -> str:
    """Add a new task to the task board.

    Only the Software Architect should use this during planning/replanning, and
    the QA Tester should use this to create 'defect' tasks.

    Args:
        id: Unique task ID, e.g., 't1', 't2', 't3-defect-1'
        title: Short title of the task
        type: Must be 'feature', 'defect', or 'chore'
        assignee_role: Must be 'frontend', 'backend', 'devops', 'dba', 'tester', or 'architect'
        priority: 'high', 'medium', or 'low'
        depends_on: List of task IDs that must be verified before this task can start
        description: Detailed instructions for the task
        context_refs: File paths or line ranges to guide the assignee (e.g. ['src/app.py:10-50'])
        acceptance_criteria: Testable criteria for verifying completion
        defect_of: If type is 'defect', the ID of the original task that failed verification
    """
    try:
        board = get_active_board()
        existing = board.get_task(id)
        if existing:
            return f"Error: Task with ID '{id}' already exists."

        valid_roles = ["architect", "frontend", "backend", "devops", "dba", "tester"]
        if assignee_role not in valid_roles:
            return f"Error: Invalid assignee_role '{assignee_role}'. Must be one of {valid_roles}."

        valid_types = ["feature", "defect", "chore"]
        if type not in valid_types:
            return f"Error: Invalid type '{type}'. Must be one of {valid_types}."

        board.add_task(
            id=id,
            title=title,
            type=type,
            assignee_role=assignee_role,
            status="pending",
            priority=priority,
            depends_on=depends_on,
            description=description,
            context_refs=context_refs,
            acceptance_criteria=acceptance_criteria,
            created_by="agent",
            defect_of=defect_of,
        )
        return f"Successfully added task '{id}': {title}"
    except Exception as e:
        return f"Error adding task: {e}"


@tool
def update_task_status(
    task_id: str,
    status: str,
    result_summary: Optional[str] = None,
    diff_ref: Optional[str] = None,
) -> str:
    """Update the status of a task on the board.

    Use this to move a task to 'in_progress', 'complete', or 'verified'.
    If status is set to 'complete', you must provide result_summary and diff_ref.
    If status is set to 'verified', this indicates the task passed QA testing.

    Args:
        task_id: The ID of the task to update
        status: The new status ('pending', 'in_progress', 'complete', 'verified')
        result_summary: Short summary of changes made (under 50 words). Required if status is 'complete'.
        diff_ref: Code change pointer (git branch, commit hash, patch, or 'applied'). Required if status is 'complete'.
    """
    try:
        board = get_active_board()
        task = board.get_task(task_id)
        if not task:
            return f"Error: Task '{task_id}' not found."

        valid_statuses = ["pending", "in_progress", "complete", "verified"]
        if status not in valid_statuses:
            return f"Error: Invalid status '{status}'. Must be one of {valid_statuses}."

        updates = {"status": status}
        if result_summary is not None:
            updates["result_summary"] = result_summary
        if diff_ref is not None:
            updates["diff_ref"] = diff_ref

        board.update_task(task_id, updates)
        return f"Successfully updated task '{task_id}' status to '{status}'"
    except Exception as e:
        return f"Error updating task status: {e}"


@tool
def ask_architect_followup(task_id: str, question: str) -> str:
    """Ask the Software Architect a question regarding the task.

    Sets `needs_followup=True` on the task and flags it for the Architect.
    Leave the status as 'in_progress'. Keep the question brief.

    Args:
        task_id: The ID of the task that has a blocker/question.
        question: Concise question/clarification details.
    """
    try:
        board = get_active_board()
        task = board.get_task(task_id)
        if not task:
            return f"Error: Task '{task_id}' not found."

        board.update_task(
            task_id,
            {
                "needs_followup": True,
                "followup_question": question,
            },
        )
        return f"Successfully posted followup question to Architect for task '{task_id}'."
    except Exception as e:
        return f"Error asking Architect followup: {e}"


@tool
def answer_followup(task_id: str, answer: str) -> str:
    """Answer a developer's question on a task.

    Only the Software Architect should use this. It clears the
    `needs_followup` flag.

    Args:
        task_id: The ID of the task that had a followup question.
        answer: Concise clarification answer.
    """
    try:
        board = get_active_board()
        task = board.get_task(task_id)
        if not task:
            return f"Error: Task '{task_id}' not found."

        board.update_task(
            task_id,
            {
                "needs_followup": False,
                "followup_answer": answer,
            },
        )
        return f"Successfully answered followup for task '{task_id}'."
    except Exception as e:
        return f"Error answering followup: {e}"


# Return all board-related tools
def get_board_tools() -> List[Any]:
    """Get all board-related tools."""
    return [
        view_task_board,
        add_task,
        update_task_status,
        ask_architect_followup,
        answer_followup,
    ]
