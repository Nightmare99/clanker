"""Orchestrator for MNQ multi-agent mode execution."""

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.table import Table

from clanker.agent.mnq.agent import run_role_agent
from clanker.agent.mnq.board import TaskBoard
from clanker.agent.mnq.roles import ROLE_METADATA
from clanker.agent.mnq.tools import set_active_board
from clanker.config import Settings
from clanker.logging import get_logger
from clanker.ui.console import Console

logger = get_logger("orchestrator.mnq")


def resolve_context_refs(context_refs: List[str]) -> str:
    """Read and format the content of the specified context references.

    Args:
        context_refs: List of file references (e.g., 'src/main.py:1-50', 'tests/test_main.py').

    Returns:
        Formatted string containing the file contents.
    """
    if not context_refs:
        return "No files specified in context_refs."

    resolved_text = []
    for ref in context_refs:
        parts = ref.split(":")
        path_str = parts[0].strip()
        line_range = parts[1].strip() if len(parts) > 1 else None

        path = Path(path_str)
        if not path.exists() or not path.is_file():
            resolved_text.append(f"File '{path_str}' not found on disk.")
            continue

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            if line_range:
                range_parts = line_range.split("-")
                start = int(range_parts[0]) - 1
                end = int(range_parts[1]) if len(range_parts) > 1 else len(lines)
                # Ensure indices are within bounds
                start = max(0, start)
                end = min(len(lines), end)
                selected_lines = lines[start:end]
                content = "".join(selected_lines)
                resolved_text.append(
                    f"### File: {path_str} (Lines {line_range})\n```\n{content}\n```"
                )
            else:
                # Read entire file up to 300 lines to keep context tight
                content = "".join(lines[:300])
                suffix = "\n... [truncated to 300 lines] ..." if len(lines) > 300 else ""
                resolved_text.append(f"### File: {path_str}\n```\n{content}{suffix}\n```")
        except Exception as e:
            resolved_text.append(f"Error reading file '{path_str}': {e}")

    return "\n\n".join(resolved_text)


class MNQOrchestrator:
    """Orchestrates planning, claim, and work cycles in MNQ multi-agent mode."""

    def __init__(self, settings: Settings, console: Console, checkpointer: Any, session_id: str = "default") -> None:
        """Initialize the orchestrator.

        Args:
            settings: Settings object.
            console: Console instance.
            checkpointer: Checkpoint saver.
            session_id: Session identifier.
        """
        self.settings = settings
        self.console = console
        self.checkpointer = checkpointer

        # Database path inside the active workspace .clanker/ folder
        workspace_dir = Path(os.getcwd())
        self.db_dir = workspace_dir / ".clanker"
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_dir / f"mnq_board_{session_id}.db"
        self.board = TaskBoard(self.db_path)

        # Register board with tools
        set_active_board(self.board)

        # Session thread_id configurations
        self.architect_thread_id = f"mnq_architect_{session_id}"
        self.engineer_thread_id = f"mnq_engineer_{session_id}"

    def switch_session(self, session_id: str) -> None:
        """Switch to a different session and load its corresponding database.

        Args:
            session_id: The new session ID.
        """
        self.board.close()
        self.db_path = self.db_dir / f"mnq_board_{session_id}.db"
        self.board = TaskBoard(self.db_path)
        set_active_board(self.board)
        self.architect_thread_id = f"mnq_architect_{session_id}"
        self.engineer_thread_id = f"mnq_engineer_{session_id}"

    def format_board_summary(self) -> str:
        """Create a compact text summary of the board state for model prompt context.

        Returns:
            Formatted board summary string.
        """
        tasks = self.board.get_tasks()
        if not tasks:
            return "Task Board is currently empty."

        lines = ["Current Tasks:"]
        for t in tasks:
            deps = f" depends_on={t['depends_on']}" if t["depends_on"] else ""
            summary = f" result_summary='{t['result_summary']}'" if t["result_summary"] else ""
            defect = f" defect_of={t['defect_of']}" if t["defect_of"] else ""
            lines.append(
                f"- [{t['id']}] {t['title']} ({t['type']}) -> role={t['assignee_role']}, status={t['status']}{deps}{defect}{summary}"
            )
        return "\n".join(lines)

    def print_fancy_board(self) -> None:
        """Print the current task board to the console using a rich table."""
        tasks = self.board.get_tasks()
        if not tasks:
            self.console.print_info("Task Board is empty.")
            return

        table = Table(title="📋 MNQ Task Board", show_header=True, header_style="bold magenta")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Title", style="white")
        table.add_column("Assignee", style="yellow")
        table.add_column("Status", style="bold green")
        table.add_column("Depends On", style="dim")
        table.add_column("Followup", style="red")

        for t in tasks:
            status_color = {
                "backlog": "dim",
                "pending": "blue",
                "in_progress": "yellow",
                "complete": "cyan",
                "verified": "bold green",
                "defect": "bold red",
            }.get(t["status"], "white")

            followup = "⚠️ Question" if t["needs_followup"] else ""
            deps = ", ".join(t["depends_on"]) if t["depends_on"] else "-"

            table.add_row(
                t["id"],
                t["title"],
                ROLE_METADATA.get(t["assignee_role"], {}).get("name", t["assignee_role"]),
                f"[{status_color}]{t['status']}[/{status_color}]",
                deps,
                followup,
            )

        self.console._console.print(table)

    def run_initial_planning(self, user_request: str) -> bool:
        """Run the Software Architect to inspect the codebase and plan tasks.

        Args:
            user_request: The user's goal prompt.

        Returns:
            True if tasks were added, False otherwise.
        """
        self.console.print_notify(
            "📐 Software Architect exploring repo and planning tasks...", "info", "Planning Phase"
        )
        self.board.clear()

        # Let the architect explore the repo structure and create tasks
        arch_config = {"configurable": {"thread_id": self.architect_thread_id}}

        # Context layout for Architect: user request + list of repository contents
        repo_files = []
        for root, dirs, files in os.walk("."):
            # Skip hidden folders
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), ".")
                repo_files.append(rel_path)

        repo_tree = "\n".join(repo_files[:100])  # limit file list size to fit token budget
        task_desc = (
            f"User Goal: {user_request}\n\n"
            f"Repository file listing (first 100 files):\n{repo_tree}\n\n"
            "Please analyze this structure, draft tasks, and use the `add_task` tool to "
            "populate the task board. Ensure you create at least one task."
        )

        run_role_agent(
            role="architect",
            task_description=task_desc,
            board_summary="Task Board is empty.",
            settings=self.settings,
            checkpointer=self.checkpointer,
            config=arch_config,
            console=self.console,
        )

        # Check if tasks were created
        tasks = self.board.get_tasks()
        if not tasks:
            self.console.print_error(
                "Architect failed to create any tasks on the board. Cannot proceed."
            )
            return False

        self.console.print_success(f"Architect generated {len(tasks)} tasks.")
        self.print_fancy_board()
        return True

    def handle_followups(self) -> None:
        """Check for tasks requiring Architect followup and run the Architect to address them."""
        tasks = self.board.get_tasks()
        followups = [t for t in tasks if t["needs_followup"]]

        for t in followups:
            self.console.print_notify(
                f"📐 Software Architect addressing followup for task '{t['id']}'...",
                "info",
                "Followup Phase",
            )
            arch_config = {"configurable": {"thread_id": self.architect_thread_id}}
            board_summary = self.format_board_summary()

            task_desc = (
                f"Clarification requested for Task ID '{t['id']}' ({t['title']}).\n"
                f"Question from developer: {t['followup_question']}\n\n"
                "Please call `answer_followup` to provide the explanation and update the task. "
                "You may also update or create tasks on the board if requirements have changed."
            )

            run_role_agent(
                role="architect",
                task_description=task_desc,
                board_summary=board_summary,
                settings=self.settings,
                checkpointer=self.checkpointer,
                config=arch_config,
                console=self.console,
            )

    def execute_workflow(self) -> None:
        """Run the main pull-based multi-agent execution loop."""
        # Reset any tasks that were left in_progress from an interrupted run back to pending
        in_progress_tasks = self.board.get_tasks(status="in_progress")
        if in_progress_tasks:
            self.console.print_info("Resetting interrupted tasks to pending status...")
            for task in in_progress_tasks:
                logger.info("Resetting interrupted task '%s' from in_progress to pending", task["id"])
                self.board.update_task(task["id"], {"status": "pending"})
            self.print_fancy_board()

        iteration = 0
        max_iterations = 50  # Prevent infinite loop safety

        while self.board.has_unverified_tasks() and iteration < max_iterations:
            iteration += 1
            logger.info("Orchestration iteration %d starting", iteration)

            # 1. Address any developer follow-ups/clarifications first
            self.handle_followups()

            # 2. Find runnable engineering tasks (status='pending' and dependencies verified)
            runnable_found = False
            for role in ["dba", "devops", "backend", "frontend"]:
                runnable_tasks = self.board.get_runnable_tasks(role)
                if not runnable_tasks:
                    continue

                runnable_found = True
                for task in runnable_tasks:
                    task_id = task["id"]
                    # Try to atomically claim the task
                    if not self.board.claim_task(role, task_id):
                        # Another worker claimed it or it is no longer pending
                        continue

                    # Claim succeeded! Work the task.
                    metadata = ROLE_METADATA.get(role, {})
                    self.console.print_notify(
                        f"Claimed Task '{task_id}': {task['title']}",
                        "info",
                        f"{metadata.get('name', role)} {metadata.get('icon', '')}",
                    )

                    # Resolve starting context files
                    files_content = resolve_context_refs(task["context_refs"])

                    # Build prompt details
                    task_desc = (
                        f"You have claimed Task '{task_id}': {task['title']}\n"
                        f"Description: {task['description']}\n"
                        f"Acceptance Criteria:\n"
                    )
                    for ac in task["acceptance_criteria"]:
                        task_desc += f"- {ac}\n"

                    task_desc += (
                        f"\nResolved Starting Context File Contents:\n{files_content}\n\n"
                        "Please implement the changes requested. Explore files further if needed. "
                        "Once you are done, run tests or verify your work, and use the "
                        "`update_task_status` tool to mark this task as 'complete' (provide a "
                        "result_summary under 50 words and diff_ref, e.g. 'applied')."
                    )

                    # Run engineer task agent (fresh, isolated history per turn)
                    eng_config = {"configurable": {"thread_id": f"mnq_eng_{task_id}"}}
                    board_summary = self.format_board_summary()

                    run_role_agent(
                        role=role,
                        task_description=task_desc,
                        board_summary=board_summary,
                        settings=self.settings,
                        checkpointer=self.checkpointer,
                        config=eng_config,
                        console=self.console,
                    )

                    # Update and display board state after task execution
                    self.print_fancy_board()

            # 3. Find complete tasks for Tester QA verification
            complete_tasks = self.board.get_tasks(status="complete")
            # Filter to features/chores (defects are tested too but we check original tasks)
            for task in complete_tasks:
                task_id = task["id"]
                # Atomically claim the task for QA
                if not self.board.claim_task("tester", task_id):
                    continue

                runnable_found = True
                self.console.print_notify(
                    f"Testing Task '{task_id}': {task['title']}", "info", "QA Tester 🧪"
                )

                task_desc = (
                    f"Please verify Task '{task_id}': {task['title']}\n"
                    f"Implemented by: {task['assignee_role']}\n"
                    f"Description: {task['description']}\n"
                    f"Acceptance Criteria:\n"
                )
                for ac in task["acceptance_criteria"]:
                    task_desc += f"- {ac}\n"

                task_desc += (
                    f"\nImplementation Details:\n"
                    f"Result Summary: {task['result_summary']}\n"
                    f"Diff Reference: {task['diff_ref']}\n\n"
                    "Please write and/or run verification tests (e.g. pytest or shell runs) "
                    "on the codebase. If all tests pass, call `update_task_status` to move this task "
                    "to 'verified'. If tests fail, leave this task status as 'complete' and create a "
                    "NEW task of type 'defect' using `add_task` assigned back to the developer's role, "
                    "explaining the failing tests in details in acceptance_criteria, referencing "
                    "this original task ID in `defect_of`."
                )

                tester_config = {"configurable": {"thread_id": f"mnq_tester_{task_id}"}}
                board_summary = self.format_board_summary()

                run_role_agent(
                    role="tester",
                    task_description=task_desc,
                    board_summary=board_summary,
                    settings=self.settings,
                    checkpointer=self.checkpointer,
                    config=tester_config,
                    console=self.console,
                )

                self.print_fancy_board()

                # After tester runs: if any in_progress tasks now have pending defect tasks
                # filed against them, reset them back to pending so the engineer can fix them.
                pending_defects = [
                    t for t in self.board.get_tasks(status="pending")
                    if t.get("type") == "defect"
                ]
                for defect in pending_defects:
                    for dep_id in defect.get("depends_on", []):
                        parent = self.board.get_task(dep_id)
                        if parent and parent["status"] == "in_progress":
                            logger.info(
                                "Resetting task '%s' from in_progress to pending "
                                "because defect '%s' was filed against it",
                                dep_id, defect["id"],
                            )
                            self.board.update_task(dep_id, {"status": "pending"})
                            self.console.print_info(
                                f"🔄 Task '{dep_id}' reset to pending — "
                                f"defect '{defect['id']}' filed by QA."
                            )
                if pending_defects:
                    self.print_fancy_board()

            # 4. Handle deadlock or blocked states
            if not runnable_found:
                # Let's check if all tasks are verified
                if not self.board.has_unverified_tasks():
                    break

                # We have unverified tasks but no runnable or completed tasks
                # Check if we have blocked tasks with dependencies
                pending_tasks = self.board.get_tasks(status="pending")
                if pending_tasks:
                    self.console.print_error(
                        "⚠️ DEADLOCK DETECTED! No tasks can run due to unmet dependencies. "
                        "Please inspect the board and resolve manual constraints."
                    )
                    self.print_fancy_board()
                    break
                else:
                    self.console.print_warning(
                        "No runnable tasks found. Sleeping and checking again..."
                    )
                    time.sleep(2)

        if not self.board.has_unverified_tasks():
            self.console.print_success("🎉 All tasks on the board are successfully verified!")
        else:
            self.console.print_error("MNQ execution loop terminated with outstanding tasks.")
