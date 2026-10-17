"""Task-local working directory and cooperative cancellation for tools."""

import asyncio
import os
import signal
import subprocess
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

task_directory: ContextVar[str | None] = ContextVar("task_directory", default=None)
task_memory_directory: ContextVar[str | None] = ContextVar("task_memory_directory", default=None)
task_stop: ContextVar[threading.Event | None] = ContextVar("task_stop", default=None)


@dataclass
class TurnCancellation:
    """A turn's stop flag and the processes that must settle before resuming."""

    stop: threading.Event = field(default_factory=threading.Event)
    processes: list[threading.Event] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def track_process(self) -> threading.Event:
        done = threading.Event()
        with self.lock:
            self.processes.append(done)
        return done

    async def settle(self) -> None:
        deadline = asyncio.get_running_loop().time() + 3
        while asyncio.get_running_loop().time() < deadline:
            with self.lock:
                pending = any(not done.is_set() for done in self.processes)
            if not pending:
                return
            await asyncio.sleep(0.01)


turn_cancellation: ContextVar[TurnCancellation | None] = ContextVar(
    "turn_cancellation", default=None,
)
_process_watchers: set[asyncio.Task[None]] = set()


def cancellation_event() -> threading.Event | None:
    turn = turn_cancellation.get()
    return task_stop.get() or (turn.stop if turn is not None else None)


@contextmanager
def process_lifetime() -> Iterator[None]:
    turn = turn_cancellation.get()
    done = turn.track_process() if turn is not None else None
    try:
        yield
    finally:
        if done is not None:
            done.set()


def kill_process_tree(pid: int) -> None:
    """Kill only the process group/tree created for an owned command."""
    with suppress(ProcessLookupError, PermissionError):
        if os.name == "posix":
            os.killpg(pid, signal.SIGKILL)
        else:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
                check=False,
            )


async def stop_process(process: asyncio.subprocess.Process) -> None:
    if os.name == "posix":
        kill_process_tree(process.pid)
    else:
        await asyncio.to_thread(kill_process_tree, process.pid)
    await process.wait()


def _process_tree_running(process: asyncio.subprocess.Process) -> bool:
    if process.returncode is None:
        return True
    if os.name == "posix":
        # A shell can exit before its children, which may still own stdout.
        try:
            os.killpg(process.pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            pass
    return False


def watch_process(
    process: asyncio.subprocess.Process, on_cancel: Callable[[], None] | None = None,
) -> None:
    """Keep promoted/background commands owned by the turn that started them."""
    stop = cancellation_event()
    if stop is None:
        return
    turn = turn_cancellation.get()
    done = turn.track_process() if turn is not None else None

    async def watch() -> None:
        try:
            while _process_tree_running(process):
                if stop.is_set():
                    if on_cancel is not None:
                        on_cancel()
                    await stop_process(process)
                    return
                await asyncio.sleep(0.025)
        finally:
            if done is not None:
                done.set()

    task = asyncio.create_task(watch())
    _process_watchers.add(task)
    task.add_done_callback(_process_watchers.discard)
task_interaction: ContextVar[Callable[..., dict[str, Any]] | None] = ContextVar(
    "task_interaction", default=None
)


def working_directory() -> str:
    return task_directory.get() or os.getcwd()


def memory_directory() -> str:
    """Keep worktree subagents on their parent's workspace memory scope."""
    return task_memory_directory.get() or working_directory()


def check_cancelled() -> None:
    stop = cancellation_event()
    if stop is not None and stop.is_set():
        raise ValueError("Task stopped; no further changes are allowed.")
