"""SQLite-based task board for MNQ multi-agent mode."""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


class TaskBoard:
    """Shared, persistent Jira-style task board using SQLite."""

    def __init__(self, db_path: Path) -> None:
        """Initialize the task board and ensure the schema exists.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        """Create the tasks table if it does not exist."""
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    type TEXT NOT NULL,          -- feature | defect | chore
                    assignee_role TEXT NOT NULL,  -- architect | frontend | backend | devops | dba | tester
                    status TEXT NOT NULL,         -- backlog | pending | in_progress | complete | verified | defect
                    priority TEXT NOT NULL,       -- high | medium | low
                    depends_on TEXT,              -- JSON array of task IDs
                    description TEXT,
                    context_refs TEXT,            -- JSON array of file paths / line ranges
                    acceptance_criteria TEXT,     -- JSON array of strings
                    created_by TEXT NOT NULL,
                    result_summary TEXT,          -- Capped summary
                    diff_ref TEXT,                -- Git ref, patch ID, or worktree path
                    defect_of TEXT,               -- Original task ID if type=defect
                    tokens_used INTEGER DEFAULT 0,
                    needs_followup INTEGER DEFAULT 0,
                    followup_question TEXT,
                    followup_answer TEXT
                )
            """)

    def clear(self) -> None:
        """Clear all tasks from the board."""
        with self.conn:
            self.conn.execute("DELETE FROM tasks")

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a SQLite Row into a task dictionary with parsed JSON fields."""
        d = dict(row)
        # Parse JSON fields
        for field in ("depends_on", "context_refs", "acceptance_criteria"):
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except Exception:
                    d[field] = []
            else:
                d[field] = []
        # Convert integer boolean
        d["needs_followup"] = bool(d.get("needs_followup"))
        return d

    def add_task(
        self,
        id: str,
        title: str,
        type: str,
        assignee_role: str,
        status: str,
        priority: str,
        depends_on: List[str],
        description: str,
        context_refs: List[str],
        acceptance_criteria: List[str],
        created_by: str,
        defect_of: Optional[str] = None,
    ) -> None:
        """Add a new task to the board.

        Args:
            id: Unique task ID (e.g. t1, t2).
            title: Short description of the task.
            type: "feature" | "defect" | "chore".
            assignee_role: Role assigned to work the task.
            status: Initial status (e.g., "pending").
            priority: Priority level.
            depends_on: List of task IDs this task depends on.
            description: Detailed task description.
            context_refs: List of source code files/ranges.
            acceptance_criteria: Conditions of acceptance.
            created_by: Subagent/role that created the task.
            defect_of: Parent task ID if this is a defect task.
        """
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO tasks (
                    id, title, type, assignee_role, status, priority, depends_on,
                    description, context_refs, acceptance_criteria, created_by, defect_of
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    id,
                    title,
                    type,
                    assignee_role,
                    status,
                    priority,
                    json.dumps(depends_on),
                    description,
                    json.dumps(context_refs),
                    json.dumps(acceptance_criteria),
                    created_by,
                    defect_of,
                ),
            )

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a task by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        if row:
            return self._row_to_dict(row)
        return None

    def update_task(self, task_id: str, updates: Dict[str, Any]) -> None:
        """Update fields of an existing task.

        Args:
            task_id: ID of the task to update.
            updates: Dictionary of field name to new value.
        """
        if not updates:
            return

        set_clauses = []
        params = []
        for key, value in updates.items():
            if key in ("depends_on", "context_refs", "acceptance_criteria"):
                value = json.dumps(value)
            elif key == "needs_followup":
                value = 1 if value else 0
            set_clauses.append(f"{key} = ?")
            params.append(value)

        params.append(task_id)
        query = f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = ?"

        with self.conn:
            self.conn.execute(query, tuple(params))

    def claim_task(self, role: str, task_id: str) -> bool:
        """Atomically claim a pending task for a role, or a completed task for the tester.

        Updates status to 'in_progress'.

        Args:
            role: The role claiming the task.
            task_id: The ID of the task to claim.

        Returns:
            True if the task was successfully claimed, False otherwise.
        """
        with self.conn:
            if role == "tester":
                cursor = self.conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'in_progress'
                    WHERE id = ? AND status = 'complete'
                    """,
                    (task_id,),
                )
            else:
                cursor = self.conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'in_progress'
                    WHERE id = ? AND assignee_role = ? AND status = 'pending'
                    """,
                    (task_id, role),
                )
            return cursor.rowcount > 0

    def get_tasks(
        self, filter_role: Optional[str] = None, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve all tasks on the board, optionally filtered by role and/or status.

        Args:
            filter_role: Optional role name.
            status: Optional status string.

        Returns:
            List of task dictionaries.
        """
        cursor = self.conn.cursor()
        query = "SELECT * FROM tasks"
        where_clauses = []
        params = []

        if filter_role:
            where_clauses.append("assignee_role = ?")
            params.append(filter_role)
        if status:
            where_clauses.append("status = ?")
            params.append(status)

        if where_clauses:
            query += f" WHERE {' AND '.join(where_clauses)}"

        cursor.execute(query, tuple(params))
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def is_dependency_satisfied(self, task: Dict[str, Any]) -> bool:
        """Check if all dependencies for a task are satisfied.

        For normal tasks, all dependencies must be 'verified'.
        For defect tasks (type='defect'), a dependency is satisfied if the
        parent is in any active state (in_progress, complete, verified) —
        this allows defect fix tasks to run while the parent is being reworked.

        Args:
            task: Task dictionary.

        Returns:
            True if all tasks in depends_on are satisfied, or if
            there are no dependencies.
        """
        dep_ids = task.get("depends_on", [])
        if not dep_ids:
            return True

        is_defect = task.get("type") == "defect"
        # Statuses that count as "satisfied" for defect tasks
        defect_ok_statuses = {"in_progress", "complete", "verified"}

        for dep_id in dep_ids:
            dep = self.get_task(dep_id)
            if not dep:
                return False
            if is_defect:
                if dep["status"] not in defect_ok_statuses:
                    return False
            else:
                if dep["status"] != "verified":
                    return False
        return True

    def get_runnable_tasks(self, role: str) -> List[Dict[str, Any]]:
        """Get all pending tasks for a role whose dependencies are satisfied.

        Args:
            role: The role to query.

        Returns:
            List of runnable tasks.
        """
        pending = self.get_tasks(filter_role=role, status="pending")
        return [t for t in pending if self.is_dependency_satisfied(t)]

    def has_unverified_tasks(self) -> bool:
        """Check if there are any non-verified/non-defect features on the board.

        Returns:
            True if there are tasks that are not yet verified.
        """
        cursor = self.conn.cursor()
        # Anything not 'verified' (and not 'defect' status)
        cursor.execute("SELECT COUNT(*) FROM tasks WHERE status != 'verified'")
        count = cursor.fetchone()[0]
        return count > 0
