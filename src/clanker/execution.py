"""Task-local working directory and cooperative cancellation for tools."""

import os
import threading
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

task_directory: ContextVar[str | None] = ContextVar("task_directory", default=None)
task_stop: ContextVar[threading.Event | None] = ContextVar("task_stop", default=None)
task_interaction: ContextVar[Callable[..., dict[str, Any]] | None] = ContextVar(
    "task_interaction", default=None
)


def working_directory() -> str:
    return task_directory.get() or os.getcwd()


def check_cancelled() -> None:
    stop = task_stop.get()
    if stop is not None and stop.is_set():
        raise ValueError("Task stopped; no further changes are allowed.")
