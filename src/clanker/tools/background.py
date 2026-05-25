"""Background bash jobs.

Lets the agent launch long-running shell commands without blocking its
turn. Each job runs in its own process group, with output streamed to
both an on-disk log and a bounded in-memory tail buffer. The agent can
poll status, fetch (incremental) output, and kill jobs by job id.

All subprocess I/O (launch, drain, kill) runs on a single dedicated
event loop hosted on a daemon thread. This decouples job lifetime from
any short-lived loop that callers (sync `execute_shell`, async agent
tools) happen to be using.

Lifecycle: jobs are session-scoped. On clean CLI shutdown, any still-
running jobs receive SIGTERM (best-effort).
"""

from __future__ import annotations

import asyncio
import atexit
import os
import secrets
import signal
import tempfile
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, TypeVar

from langchain.tools import tool

from clanker.logging import get_logger
from clanker.tools.bash_tools import _get_clean_env, run_safety_checks

logger = get_logger("tools.background")

# In-memory tail buffer cap per job. Older bytes are dropped from memory
# but remain in the on-disk log.
TAIL_BUFFER_BYTES = 256 * 1024  # 256 KB

# Default soft cap for a single bash_output read response.
DEFAULT_OUTPUT_READ_BYTES = 32 * 1024  # 32 KB

_JOB_LOG_DIR = Path(tempfile.gettempdir()) / "clanker-jobs"

T = TypeVar("T")


@dataclass
class Job:
    """A background shell job."""

    id: str
    command: str
    log_path: Path
    process: asyncio.subprocess.Process
    started_at: float
    name: str | None = None  # human-readable label, agent-provided
    state: str = "running"  # running | exited | killed | timed_out | failed
    returncode: int | None = None
    ended_at: float | None = None
    bytes_written: int = 0
    tail: bytearray = field(default_factory=bytearray)
    _reader_task: asyncio.Task | None = None
    _timeout_handle: asyncio.TimerHandle | None = None
    _done: asyncio.Event | None = None  # set when state leaves "running"

    def append_chunk(self, data: bytes) -> None:
        self.bytes_written += len(data)
        self.tail.extend(data)
        overflow = len(self.tail) - TAIL_BUFFER_BYTES
        if overflow > 0:
            del self.tail[:overflow]

    def status_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "name": self.name,
            "command": self.command,
            "state": self.state,
            "returncode": self.returncode,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "runtime_seconds": round(
                (self.ended_at or time.time()) - self.started_at, 2
            ),
            "bytes_captured": self.bytes_written,
            "log_path": str(self.log_path),
        }


class JobManager:
    """Process-wide registry of background jobs.

    Owns a dedicated asyncio event loop on a daemon thread. All
    subprocess I/O is performed on that loop so jobs survive whatever
    short-lived loops the calling tools happen to use.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        _JOB_LOG_DIR.mkdir(parents=True, exist_ok=True)

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="clanker-jobs", daemon=True
        )
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def submit(self, coro: Awaitable[T]) -> Future[T]:
        """Schedule a coroutine on the manager's loop, return a Future."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def run(self, coro: Awaitable[T], timeout: float | None = None) -> T:
        """Schedule a coroutine and block until it completes."""
        return self.submit(coro).result(timeout=timeout)

    @staticmethod
    def _new_id() -> str:
        return f"bg_{secrets.token_hex(3)}"

    @staticmethod
    def _sanitize_name(name: str | None, command: str = "") -> str | None:
        """Clean an agent-supplied job name, falling back to the command.

        Returns None only if both `name` and `command` are unusable.
        """
        candidates = (name, command)
        for raw in candidates:
            if raw is None:
                continue
            cleaned = " ".join(raw.strip().split())
            if not cleaned:
                continue
            if len(cleaned) > 60:
                cleaned = cleaned[:57] + "..."
            return cleaned
        return None

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        # Newest first
        return sorted(self._jobs.values(), key=lambda j: j.started_at, reverse=True)

    # ------------------------------------------------------------------
    # Coroutines (run on the manager loop)
    # ------------------------------------------------------------------

    async def _launch_coro(
        self, command: str, timeout: int | None, name: str | None
    ) -> Job:
        job_id = self._new_id()
        while job_id in self._jobs:
            job_id = self._new_id()

        log_path = _JOB_LOG_DIR / f"{job_id}.log"
        log_path.touch()

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=_get_clean_env(),
            start_new_session=True,
        )

        job = Job(
            id=job_id,
            command=command,
            log_path=log_path,
            process=process,
            started_at=time.time(),
            name=self._sanitize_name(name, command),
        )
        job._done = asyncio.Event()

        loop = asyncio.get_running_loop()
        job._reader_task = loop.create_task(self._drain(job))

        if timeout and timeout > 0:
            job._timeout_handle = loop.call_later(
                timeout, lambda: loop.create_task(self._on_timeout(job))
            )

        self._jobs[job_id] = job
        logger.info(
            "Launched background job %s (%s): %s",
            job_id,
            job.name or "-",
            command[:80],
        )
        return job

    async def _adopt_coro(
        self,
        command: str,
        process: asyncio.subprocess.Process,
        started_at: float,
        captured: bytes,
        name: str | None = None,
    ) -> Job:
        job_id = self._new_id()
        while job_id in self._jobs:
            job_id = self._new_id()

        log_path = _JOB_LOG_DIR / f"{job_id}.log"
        log_path.write_bytes(captured)

        job = Job(
            id=job_id,
            command=command,
            log_path=log_path,
            process=process,
            started_at=started_at,
            name=self._sanitize_name(name, command),
        )
        job._done = asyncio.Event()
        if captured:
            job.append_chunk(captured)

        loop = asyncio.get_running_loop()
        job._reader_task = loop.create_task(self._drain(job, append_mode=True))

        self._jobs[job_id] = job
        logger.info(
            "Adopted background job %s (%s; promoted from foreground): %s",
            job_id,
            job.name or "-",
            command[:80],
        )
        return job

    async def _drain(self, job: Job, append_mode: bool = False) -> None:
        """Continuously read child stdout into memory + disk."""
        assert job.process.stdout is not None
        mode = "ab" if append_mode else "wb"
        try:
            with job.log_path.open(mode, buffering=0) as fh:
                while True:
                    chunk = await job.process.stdout.read(4096)
                    if not chunk:
                        break
                    fh.write(chunk)
                    job.append_chunk(chunk)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Reader for %s crashed: %s", job.id, exc)

        rc = await job.process.wait()
        job.returncode = rc
        job.ended_at = time.time()
        if job.state == "running":
            job.state = "exited" if rc == 0 else "failed"

        if job._timeout_handle is not None:
            job._timeout_handle.cancel()
            job._timeout_handle = None

        logger.info(
            "Job %s finished: state=%s rc=%s bytes=%d",
            job.id,
            job.state,
            rc,
            job.bytes_written,
        )

        if job._done is not None:
            job._done.set()

    async def _on_timeout(self, job: Job) -> None:
        if job.state != "running":
            return
        logger.warning("Job %s timed out; killing", job.id)
        job.state = "timed_out"
        await self._terminate(job)

    async def _terminate(self, job: Job) -> None:
        """SIGTERM the process group, SIGKILL after a grace period."""
        if job.process.returncode is not None:
            return
        pid = job.process.pid
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            await asyncio.wait_for(job.process.wait(), timeout=2.0)
            return
        except asyncio.TimeoutError:
            pass
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    async def _kill_coro(self, job_id: str) -> str:
        job = self.get(job_id)
        if job is None:
            return f"Error: unknown job_id '{job_id}'"
        if job.state != "running":
            return f"Job {job_id} is not running (state={job.state})"
        job.state = "killed"
        await self._terminate(job)
        return f"Job {job_id} killed"

    async def _wait_coro(self, job_id: str, timeout: float | None) -> tuple[Job | None, bool]:
        """Wait until job leaves "running". Returns (job, finished).

        `finished` is True if the job is no longer running, False if the
        wait timed out. Returns (None, False) for an unknown job id.
        """
        job = self.get(job_id)
        if job is None:
            return None, False
        if job.state != "running" or job._done is None:
            return job, True
        try:
            if timeout is None:
                await job._done.wait()
            else:
                await asyncio.wait_for(job._done.wait(), timeout=timeout)
            return job, True
        except asyncio.TimeoutError:
            return job, False

    # ------------------------------------------------------------------
    # Public API (thread-safe; schedules on the manager loop)
    # ------------------------------------------------------------------

    async def launch(
        self, command: str, timeout: int | None, name: str | None = None
    ) -> Job:
        return await asyncio.wrap_future(
            self.submit(self._launch_coro(command, timeout, name))
        )

    async def adopt(
        self,
        command: str,
        process: asyncio.subprocess.Process,
        started_at: float,
        captured: bytes = b"",
        name: str | None = None,
    ) -> Job:
        return await asyncio.wrap_future(
            self.submit(self._adopt_coro(command, process, started_at, captured, name))
        )

    async def kill(self, job_id: str) -> str:
        return await asyncio.wrap_future(self.submit(self._kill_coro(job_id)))

    async def wait(
        self, job_id: str, timeout: float | None
    ) -> tuple[Job | None, bool]:
        return await asyncio.wrap_future(
            self.submit(self._wait_coro(job_id, timeout))
        )

    async def shutdown(self) -> None:
        async def _do() -> None:
            running = [j for j in self._jobs.values() if j.state == "running"]
            for job in running:
                job.state = "killed"
                try:
                    await self._terminate(job)
                except Exception:  # noqa: BLE001
                    pass

        await asyncio.wrap_future(self.submit(_do()))


_manager: JobManager | None = None
_manager_lock = threading.Lock()


def get_job_manager() -> JobManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = JobManager()
            atexit.register(_atexit_cleanup)
        return _manager


def _atexit_cleanup() -> None:
    """Best-effort: SIGTERM any still-running jobs on interpreter exit."""
    if _manager is None:
        return
    for job in _manager.all():
        if job.state != "running" or job.process.returncode is not None:
            continue
        try:
            os.killpg(os.getpgid(job.process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def _format_tail(data: bytes, tail_lines: int | None) -> str:
    text = data.decode("utf-8", errors="replace")
    if tail_lines is None or tail_lines <= 0:
        return text
    lines = text.splitlines()
    if len(lines) <= tail_lines:
        return text
    return "\n".join(lines[-tail_lines:])


@tool
async def bash_background(
    command: str, name: str | None = None, timeout: int | None = None
) -> str:
    """Launch a shell command in the background and return immediately.

    Use this for commands expected to take more than a few seconds
    (tests, builds, installs, long greps, dev servers). The agent can
    continue working and later inspect progress via `bash_status` and
    `bash_output`, or stop the job with `bash_kill`.

    Args:
        command: The shell command to run.
        name: Optional short human-readable label (e.g. "pytest suite",
            "vite dev"). Shown in status output and tool headers so it
            is easy to tell jobs apart. The opaque job id is still used
            for tracking — always pass that to other bash_* tools.
        timeout: Optional hard timeout in seconds. When exceeded, the
            job's process group is terminated and its state becomes
            "timed_out". Omit for no timeout.

    Returns:
        A short confirmation with the job id, e.g.
        "Started bg_a4f2c1 (pytest suite)".
    """
    blocked = run_safety_checks(command)
    if blocked is not None:
        return blocked

    job = await get_job_manager().launch(command, timeout, name=name)
    label = f"{job.id} ({job.name})" if job.name else job.id
    return (
        f"Started {label}\n"
        f"command: {command}\n"
        f"Use bash_status('{job.id}') or bash_output('{job.id}') to inspect."
    )


@tool
async def bash_status(job_id: str | None = None) -> str:
    """Inspect background bash jobs.

    Args:
        job_id: Specific job to inspect. If omitted, lists all jobs in
            this session (newest first).

    Returns:
        Human-readable status report. States: running, exited, failed,
        killed, timed_out.
    """
    mgr = get_job_manager()

    if job_id is None:
        jobs = mgr.all()
        if not jobs:
            return "No background jobs."
        lines = ["Background jobs (newest first):"]
        for j in jobs:
            d = j.status_dict()
            label = f" \"{j.name}\"" if j.name else ""
            cmd = j.command if len(j.command) <= 60 else j.command[:57] + "..."
            lines.append(
                f"  {d['job_id']}{label}  [{d['state']:<10}] "
                f"rc={d['returncode']} "
                f"{d['runtime_seconds']}s  "
                f"{d['bytes_captured']}B  $ {cmd}"
            )
        return "\n".join(lines)

    job = mgr.get(job_id)
    if job is None:
        return f"Error: unknown job_id '{job_id}'"

    d = job.status_dict()
    preview = _format_tail(bytes(job.tail[-512:]), tail_lines=5).strip()
    out = [
        f"job_id:      {d['job_id']}",
    ]
    if job.name:
        out.append(f"name:        {job.name}")
    out.extend([
        f"command:     {d['command']}",
        f"state:       {d['state']}",
        f"returncode:  {d['returncode']}",
        f"runtime:     {d['runtime_seconds']}s",
        f"bytes:       {d['bytes_captured']}",
        f"log_path:    {d['log_path']}",
    ])
    if preview:
        out.append("recent output:")
        out.append(preview)
    return "\n".join(out)


@tool
async def bash_output(
    job_id: str,
    tail: int | None = None,
    since_byte: int | None = None,
) -> str:
    """Read captured output from a background job.

    Args:
        job_id: The job to read.
        tail: If set, return only the last N lines.
        since_byte: If set, return bytes written after this offset (use
            the `next_byte` value from the previous read to poll
            incrementally without re-receiving old output).

    Returns:
        Captured output. The first line is a header like
        "[bg_a4f2 running, 12345 bytes, next_byte=12345]".
    """
    mgr = get_job_manager()
    job = mgr.get(job_id)
    if job is None:
        return f"Error: unknown job_id '{job_id}'"

    total = job.bytes_written

    if since_byte is not None and since_byte >= 0:
        try:
            with job.log_path.open("rb") as fh:
                fh.seek(min(since_byte, total))
                data = fh.read(DEFAULT_OUTPUT_READ_BYTES * 8)
        except OSError as exc:
            return f"Error reading log: {exc}"
        body = _format_tail(data, tail)
    else:
        body = _format_tail(bytes(job.tail), tail)
        if len(body) > DEFAULT_OUTPUT_READ_BYTES * 4:
            body = body[-DEFAULT_OUTPUT_READ_BYTES * 4 :]

    label = f"{job.id} \"{job.name}\"" if job.name else job.id
    header = (
        f"[{label} {job.state}, {total} bytes, next_byte={total}"
        + (f", rc={job.returncode}" if job.returncode is not None else "")
        + "]"
    )
    if not body.strip():
        return header + "\n(no output)"
    return header + "\n" + body


@tool
async def bash_kill(job_id: str) -> str:
    """Terminate a running background job.

    Sends SIGTERM to the job's process group, then SIGKILL after a
    short grace period if it does not exit.

    Args:
        job_id: The job to kill.

    Returns:
        Status message.
    """
    return await get_job_manager().kill(job_id)


@tool
async def bash_wait(job_id: str, timeout: float | None = 300.0) -> str:
    """Block until a background job finishes, then return its status + output.

    Use this when your next step depends on a background job's result
    and you have no other useful work to do. Prefer this over polling
    with `bash_status` in a loop — it wastes turns and tokens.

    Args:
        job_id: The job to wait for.
        timeout: Max seconds to wait. Defaults to 300 (5 minutes). Pass
            `None` for no cap (use sparingly — won't return until the
            job exits or is killed).

    Returns:
        On finish: the same block as `bash_status(job_id)` plus a tail
        of recent output, ready to read.
        On timeout: current status with a note that the job is still
        running; call `bash_wait` again to keep waiting or `bash_kill`
        to stop it.
        On unknown job_id: an error message.
    """
    mgr = get_job_manager()
    job, finished = await mgr.wait(job_id, timeout)
    if job is None:
        return f"Error: unknown job_id '{job_id}'"

    status = await bash_status.ainvoke({"job_id": job_id})
    if finished:
        return status

    return (
        status
        + f"\n\n(Job still running after {timeout}s. Call bash_wait again "
        + "to keep waiting, or bash_kill to stop it.)"
    )
