"""Managed subagent tasks with live status, follow-ups, budgets and cancellation."""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import hashlib
import io
import json
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from contextvars import copy_context
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.memory import MemorySaver

from clanker.agents import load_agent as load_agent_config
from clanker.changes import ChangeJournal, active_journal, change_actor
from clanker.config import Settings, get_settings
from clanker.execution import (
    check_cancelled,
    task_directory,
    task_interaction,
    task_stop,
    working_directory,
)
from clanker.ui.subagent_history import SubagentRun, SubagentToolCall
from clanker.ui.tool_display import normalize_tool_output

_SUBAGENT_MAX_WORDS = 800
_SUBAGENT_CONCISE_INSTRUCTIONS = """

## Output conciseness
Keep your final report concise. Include the result, changed files, checks actually
performed and unresolved issues. A successful tool call is not proof the task is
complete. Follow-up messages refine this assignment. Do not spawn nested agents
or detached shell jobs. The parent integrates and verifies your work.
"""


def _build_subagent_system_prompt(base_prompt: str) -> str:
    return base_prompt + _SUBAGENT_CONCISE_INSTRUCTIONS


def _resolve_tools(tool_names: list[str]) -> list[BaseTool]:
    from clanker.tools import get_tools

    excluded = {
        "spawn_subagent",
        "subagent_status",
        "subagent_message",
        "subagent_stop",
        "subagent_wait",
        "bash_background",
        "bash_status",
        "bash_output",
        "bash_wait",
        "bash_kill",
    }
    available = [t for t in get_tools() if t.name not in excluded]
    if not tool_names:
        return available
    requested = {name.lower() for name in tool_names}
    return [t for t in available if t.name.lower() in requested]


@dataclass
class ManagedTask:
    run: SubagentRun
    stop: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    inbox: queue.Queue[str] = field(default_factory=queue.Queue)
    reason: str = ""
    thread: threading.Thread | None = None
    cache_read: int = 0
    cache_creation: int = 0
    response_file: str | None = None
    final_status: str = "success"

    def cancel(self, reason: str = "cancelled") -> None:
        with _lock:
            if not self.done.is_set() and not self.stop.is_set():
                self.reason = reason
                self.run.status = "stopping"
                self.stop.set()

    def result(self) -> dict[str, Any]:
        run = self.run
        response = run.response
        if len(response.split()) > _SUBAGENT_MAX_WORDS:
            response = " ".join(response.split()[:_SUBAGENT_MAX_WORDS])
            response += f"\n[Output truncated. Full output saved to `{self.response_file}`.]"
        return {
            "task_id": run.task_id,
            "agent": run.agent_name,
            "status": run.status,
            "success": run.status == "success",
            "response": response,
            "error": run.error,
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
            "cost_usd": run.cost_usd,
            "elapsed_seconds": round(run.elapsed_seconds, 1),
            "timeout_seconds": run.timeout_seconds,
            "max_tokens": run.max_tokens,
            "working_directory": run.working_directory,
            "changed_files": list(run.changed_files),
            "checks": list(run.checks),
            "pending_messages": run.pending_messages,
        }


_tasks: dict[str, ManagedTask] = {}
_lock = threading.RLock()
_interaction_lock = threading.Lock()
_running = 0


def stop_task(task_id: str) -> bool:
    with _lock:
        task = _tasks.get(task_id)
        if task is None or task.done.is_set():
            return False
        task.cancel()
        return True


def send_task_message(task_id: str, message: str) -> str:
    with _lock:
        task = _tasks.get(task_id)
        if task is None:
            return "Unknown task ID"
        if task.done.is_set() or task.stop.is_set():
            return "Task has ended; spawn a new task with its result as context."
        if not message.strip():
            return "Message cannot be empty"
        task.inbox.put(message)
        task.run.messages.append(message)
        task.run.pending_messages += 1
        return "Follow-up queued"


def _stop_all() -> None:
    with _lock:
        for task in _tasks.values():
            task.cancel()


def _shutdown() -> None:
    _stop_all()
    deadline = time.monotonic() + 2
    for task in list(_tasks.values()):
        if task.thread and task.thread is not threading.current_thread():
            task.thread.join(timeout=max(0, deadline - time.monotonic()))


atexit.register(_shutdown)


def _interaction_handler(task: ManagedTask, app: Any) -> Callable[..., dict[str, Any]]:
    """Bridge synchronous tool questions to the UI without reading worker stdin."""

    def ask(question: str, options: list[str], **kwargs: Any) -> dict[str, Any]:
        cancelled = {"selected": [], "cancelled": True}
        if app is None:
            task.run.error = "This task needs user input. Resolve the question in the parent conversation and start a new task."
            task.cancel("needs_input")
            return cancelled
        from clanker.ui.task_prompt import TaskPromptScreen

        deadline = task.run.started_at + task.run.timeout_seconds

        def stopped() -> bool:
            if time.monotonic() >= deadline:
                task.cancel("timed_out")
            return task.stop.is_set()

        while not stopped():
            if _interaction_lock.acquire(timeout=0.05):
                break
        else:
            return cancelled
        screen = TaskPromptScreen(task.run.agent_name, question, options, **kwargs)
        response: list[dict[str, Any]] = []
        answered = threading.Event()

        def receive(result: dict[str, Any]) -> None:
            response.append(result)
            answered.set()

        try:
            task.run.status = "waiting"
            app.call_from_thread(app.push_screen, screen, receive)
            while not answered.wait(0.05):
                if stopped():
                    with contextlib.suppress(Exception):
                        app.call_from_thread(screen.action_cancel)
                    return cancelled
            return response[0] if response else cancelled
        finally:
            if not task.stop.is_set():
                task.run.status = "running"
            _interaction_lock.release()

    return ask


def _git(root: str, *args: str, input_bytes: bytes | None = None) -> bytes:
    check_cancelled()
    result = subprocess.run(
        ["git", "-C", root, *args], input=input_bytes, capture_output=True, timeout=60
    )
    if result.returncode:
        raise ValueError(result.stderr.decode(errors="replace").strip())
    check_cancelled()
    return result.stdout


def _create_worktree(root: str) -> str:
    """Snapshot tracked dirty changes and untracked, non-ignored files."""
    root = _git(root, "rev-parse", "--show-toplevel").decode().strip()
    destination = str(Path(tempfile.mkdtemp(prefix="clanker-task-")) / "workspace")
    try:
        _git(root, "worktree", "add", "--detach", destination, "HEAD")
        # Worktrees are deliberately retained for review/recovery, including when
        # copying the working state fails. Never discard a user's task artifacts.
        patch = _git(root, "diff", "--binary", "HEAD", "--")
        if patch:
            _git(destination, "apply", "--binary", "-", input_bytes=patch)
        for item in _git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
            check_cancelled()
            if not item:
                continue
            relative = Path(item.decode())
            source, target = Path(root) / relative, Path(destination) / relative
            if source.is_symlink():
                raise ValueError(
                    f"Worktree snapshot cannot copy untracked symlink {relative}; retained at {destination}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"Worktree retained at {destination}: {exc}") from exc
    return destination


def _event_handler(task: ManagedTask, failure_limit: int) -> Callable[[dict[str, Any]], None]:
    failures: dict[str, int] = {}

    def handle(event: dict[str, Any]) -> None:
        if task.stop.is_set():
            raise asyncio.CancelledError
        run = task.run
        kind, name = event.get("event"), event.get("name", "")
        data, run_id = event.get("data", {}), str(event.get("run_id", ""))
        if kind == "on_tool_start":
            from clanker.ui.streaming import _get_tool_arg_summary

            tool_input = data.get("input", {})
            run.tool_calls.append(
                SubagentToolCall(
                    name,
                    args=_get_tool_arg_summary(name, tool_input),
                    tool_input=tool_input,
                    run_id=run_id,
                )
            )
        elif kind == "on_tool_end":
            output = normalize_tool_output(data.get("output"))
            call = next(
                (
                    c
                    for c in reversed(run.tool_calls)
                    if c.run_id == run_id and c.status == "running"
                ),
                None,
            )
            if call is None:
                return
            from clanker.ui.tool_summary import is_failed_tool_result

            failed = output.startswith("Error:") or is_failed_tool_result(
                output, name, call.tool_input
            )
            call.output, call.status = output[:20_000], "error" if failed else "success"
            if name in ("write_file", "append_file", "edit_file"):
                journal = active_journal.get()
                if journal is not None:
                    run.changed_files = sorted(
                        {
                            str(c.path)
                            for c in journal.snapshot()
                            if c.actor == run.task_id and not c.undone
                        }
                    )
            if name == "execute_shell":
                run.checks.append(
                    {
                        "command": call.tool_input.get("command", ""),
                        "status": call.status,
                        "output": output[-4000:],
                    }
                )
            if failed:
                signature = hashlib.sha256(
                    json.dumps(
                        [name, call.tool_input, output], sort_keys=True, default=str
                    ).encode()
                ).hexdigest()
                failures[signature] = failures.get(signature, 0) + 1
                if failures[signature] >= failure_limit:
                    run.error = (
                        "Repeated identical tool failures; reassess the approach before retrying."
                    )
                    task.cancel("stalled")
            else:
                failures.clear()
        elif kind == "on_chat_model_end":
            output = data.get("output")
            usage = getattr(output, "usage_metadata", None) or {}
            if not usage:
                meta = getattr(output, "response_metadata", {}) or {}
                usage = meta.get("usage") or meta.get("token_usage") or meta
            run.input_tokens += usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
            run.output_tokens += usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
            details = usage.get("input_token_details") or {}
            task.cache_read += details.get("cache_read", 0)
            task.cache_creation += details.get("cache_creation", 0)
            if run.input_tokens + run.output_tokens >= run.max_tokens:
                task.cancel("budget_exceeded")
        if task.stop.is_set():
            raise asyncio.CancelledError

    return handle


async def _execute(task: ManagedTask, agent_config: Any, settings: Settings, console: Any) -> None:
    from clanker.ui.streaming import stream_agent_response_async

    run = task.run
    inbox: asyncio.Queue[str] = asyncio.Queue()
    checkpointer = MemorySaver()
    state = {
        "messages": [HumanMessage(content=run.prompt)],
        "working_directory": run.working_directory,
    }
    config = {"configurable": {"thread_id": run.task_id}}
    deadline = run.started_at + run.timeout_seconds

    async def watch() -> None:
        while not task.done.is_set():
            while True:
                try:
                    inbox.put_nowait(task.inbox.get_nowait())
                except queue.Empty:
                    break
            run.pending_messages = task.inbox.qsize() + inbox.qsize()
            if time.monotonic() >= deadline:
                task.cancel("timed_out")
            if task.stop.is_set():
                stream.cancel()
                return
            await asyncio.sleep(0.05)

    stream = asyncio.create_task(
        stream_agent_response_async(
            settings=settings,
            checkpointer=checkpointer,
            state=state,
            config=config,
            console=console,
            tools=_resolve_tools(agent_config.tools),
            system_prompt=_build_subagent_system_prompt(agent_config.system_prompt)
            + f"\nWorking directory: {run.working_directory}\nAll relative paths and shell commands use this directory.",
            model_name=agent_config.model,
            input_queue=inbox,
            event_callback=_event_handler(task, settings.subagents.repeated_failure_limit),
        )
    )
    watcher = asyncio.create_task(watch())
    try:
        result = await stream
        run.response = result.response
        run.input_tokens = max(
            run.input_tokens, result.cumulative_input_tokens or result.input_tokens
        )
        run.output_tokens = max(
            run.output_tokens, result.cumulative_output_tokens or result.output_tokens
        )
        task.cache_read = max(
            task.cache_read, result.cumulative_cache_read_tokens or result.cache_read_tokens
        )
        task.cache_creation = max(
            task.cache_creation,
            result.cumulative_cache_creation_tokens or result.cache_creation_tokens,
        )
        task.final_status = task.reason or result.status
        if task.final_status != "success":
            task.cancel(task.final_status)
    except asyncio.CancelledError:
        task.final_status = task.reason or "cancelled"
        task.cancel(task.final_status)
    finally:
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher


def _run(
    task: ManagedTask, agent_config: Any, settings: Settings, parent_console: Any, isolation: str
) -> None:
    global _running
    run = task.run
    acquired = False
    deadline_timer: threading.Timer | None = None
    try:
        while not task.stop.is_set():
            with _lock:
                if _running < settings.subagents.max_concurrent:
                    _running += 1
                    acquired = True
                    break
            task.stop.wait(0.05)
        if not acquired:
            task.final_status = task.reason or "cancelled"
            return
        run.started_at = time.monotonic()
        task_stop.set(task.stop)
        deadline_timer = threading.Timer(run.timeout_seconds, task.cancel, args=("timed_out",))
        deadline_timer.daemon = True
        deadline_timer.start()
        if isolation == "worktree":
            run.working_directory = _create_worktree(run.working_directory)
        task_directory.set(run.working_directory)
        task_interaction.set(
            _interaction_handler(task, getattr(parent_console, "_textual_app", None))
        )
        change_actor.set(run.task_id)
        if active_journal.get() is None:
            active_journal.set(ChangeJournal())
        if task.stop.is_set():
            task.final_status = task.reason or "cancelled"
            return
        run.status = "running"
        from clanker.ui.console import Console

        console = Console(agent_label=run.agent_name)
        console._console.file = io.StringIO()
        asyncio.run(_execute(task, agent_config, settings, console))
        if task.stop.is_set():
            task.final_status = task.reason or "cancelled"
        if len(run.response.split()) > _SUBAGENT_MAX_WORDS:
            with tempfile.NamedTemporaryFile(
                mode="w", prefix="clanker_", suffix=".md", delete=False
            ) as output:
                output.write(run.response)
                task.response_file = output.name
    except Exception as exc:
        task.final_status = task.reason or "error"
        run.error = str(exc)
    finally:
        journal = active_journal.get()
        if deadline_timer is not None:
            deadline_timer.cancel()
        if journal is not None:
            run.changed_files = sorted(
                {str(c.path) for c in journal.snapshot() if c.actor == run.task_id and not c.undone}
            )
        if acquired:
            with _lock:
                _running -= 1
        for call in run.tool_calls:
            if call.status == "running":
                call.status = "cancelled" if task.stop.is_set() else "error"
        run.ended_at = time.monotonic()
        with contextlib.suppress(Exception):
            from clanker.config import get_default_model, get_model_by_name

            model = (get_model_by_name(run.model) if run.model else None) or get_default_model()
            if model:
                run.cost_usd = model.compute_cost(
                    run.input_tokens, run.output_tokens, task.cache_read, task.cache_creation
                )
        with _lock:
            run.status = task.reason or task.final_status
            task.done.set()
        app = getattr(parent_console, "_textual_app", None)
        if app is not None:
            with contextlib.suppress(Exception):
                app.call_from_thread(app.refresh_subagent_hint)
                app.call_from_thread(
                    app.add_subagent_tokens,
                    run.input_tokens,
                    run.output_tokens,
                    task.cache_read,
                    task.cache_creation,
                    run.cost_usd,
                )


@tool
async def spawn_subagent(
    agent_name: str,
    prompt: str,
    background: bool = False,
    isolation: Literal["shared", "worktree"] = "shared",
    timeout_seconds: int | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Start a managed task using a configured agent.

    Set background=True to receive a task_id immediately and continue other work.
    Use subagent_status/wait/message/stop with that ID. Use isolation='worktree'
    for concurrent writers: snapshots the repository's current changes into a
    separate retained Git worktree. The parent reviews and integrates its files.
    Shared tasks must have non-overlapping edits. Worktrees separate files, not
    OS permissions. Token budgets are checked after each model response and may
    overshoot by one response. Time limits start when the task leaves the queue.
    """
    from clanker.ui.streaming import get_active_console

    root = working_directory()
    agent_config = load_agent_config(agent_name, root)
    if agent_config is None:
        return {"success": False, "error": f"Agent '{agent_name}' not found."}
    settings = get_settings()
    timeout_seconds = (
        timeout_seconds if timeout_seconds is not None else settings.subagents.timeout_seconds
    )
    max_tokens = max_tokens if max_tokens is not None else settings.subagents.max_tokens
    if timeout_seconds <= 0 or max_tokens <= 0:
        return {"success": False, "error": "Time and token budgets must be positive."}
    run = SubagentRun(
        agent_name=agent_name,
        prompt=prompt,
        status="queued",
        timeout_seconds=min(timeout_seconds, settings.subagents.timeout_seconds),
        max_tokens=min(max_tokens, settings.subagents.max_tokens),
        working_directory=root,
        model=agent_config.model,
    )
    task = ManagedTask(run)
    with _lock:
        _tasks[run.task_id] = task
    parent_console = get_active_console()
    app = getattr(parent_console, "_textual_app", None)
    if app is not None:
        app.register_subagent_run(run)
    context = copy_context()
    task.thread = threading.Thread(
        target=context.run,
        args=(_run, task, agent_config, settings, parent_console, isolation),
        daemon=True,
    )
    task.thread.start()
    if background:
        return task.result()
    try:
        while not task.done.is_set():
            await asyncio.sleep(0.05)
    except asyncio.CancelledError:
        task.cancel()
        raise
    return task.result()


@tool
def subagent_status(task_id: str | None = None) -> dict[str, Any]:
    """Get a task's result, evidence and budgets, or list all session tasks."""
    with _lock:
        if task_id is None:
            return {"tasks": [t.result() for t in _tasks.values()]}
        task = _tasks.get(task_id)
        return task.result() if task else {"success": False, "error": "Unknown task ID"}


@tool
def subagent_message(task_id: str, message: str) -> dict[str, Any]:
    """Queue a follow-up for a running task, injected at its next model boundary."""
    result = send_task_message(task_id, message)
    return {"success": result == "Follow-up queued", "task_id": task_id, "message": result}


@tool
def subagent_stop(task_id: str) -> dict[str, Any]:
    """Request cancellation of a task and its owned shell command."""
    return {"success": stop_task(task_id), "task_id": task_id}


@tool
async def subagent_wait(task_id: str, timeout_seconds: int = 30) -> dict[str, Any]:
    """Wait up to 60 seconds for a task, returning its current status or result."""
    with _lock:
        task = _tasks.get(task_id)
    if task is None:
        return {"success": False, "error": "Unknown task ID"}
    deadline = time.monotonic() + min(max(timeout_seconds, 0), 60)
    while not task.done.is_set() and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    return task.result()
