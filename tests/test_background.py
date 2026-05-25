"""Tests for background bash job tools."""

from __future__ import annotations

import asyncio

import pytest

from clanker.config import get_settings
from clanker.tools import background as bg
from clanker.tools.background import (
    JobManager,
    bash_background,
    bash_kill,
    bash_output,
    bash_status,
    bash_wait,
)


@pytest.fixture(autouse=True)
def _disable_safety():
    """Disable sandbox + confirmation so tests can run arbitrary commands."""
    settings = get_settings()
    prev_sandbox = settings.safety.sandbox_commands
    prev_confirm = settings.safety.require_confirmation
    settings.safety.sandbox_commands = False
    settings.safety.require_confirmation = False
    yield
    settings.safety.sandbox_commands = prev_sandbox
    settings.safety.require_confirmation = prev_confirm


@pytest.fixture(autouse=True)
def _fresh_manager(monkeypatch, tmp_path):
    """Give each test its own JobManager rooted at a tmp log dir."""
    monkeypatch.setattr(bg, "_JOB_LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(bg, "_manager", None)
    yield
    # Best-effort cleanup of any still-running jobs.
    mgr = bg._manager
    if mgr is not None:
        for job in list(mgr.all()):
            if job.state == "running":
                try:
                    asyncio.get_event_loop().run_until_complete(mgr._terminate(job))
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _job_id_from_launch(text: str) -> str:
    # Launch message begins with "Started <id>" or "Started <id> (name)"
    first = text.splitlines()[0]
    for tok in first.split():
        if tok.startswith("bg_"):
            return tok
    raise AssertionError(f"No job id found in: {first!r}")


async def _wait_until(predicate, *, timeout: float = 5.0, interval: float = 0.05):
    """Poll predicate() until truthy or timeout."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# Launch & basic lifecycle
# ---------------------------------------------------------------------------


class TestLaunchAndLifecycle:
    async def test_background_returns_job_id_immediately(self):
        msg = await bash_background.ainvoke({"command": "sleep 0.2"})
        assert msg.startswith("Started bg_")
        jid = _job_id_from_launch(msg)
        assert jid.startswith("bg_")
        # Manager should know about it right away.
        assert bg.get_job_manager().get(jid) is not None

    async def test_quick_command_exits_cleanly(self):
        msg = await bash_background.ainvoke({"command": "echo hello"})
        jid = _job_id_from_launch(msg)
        job = bg.get_job_manager().get(jid)
        assert job is not None
        ok = await _wait_until(lambda: job.state != "running")
        assert ok, "job did not finish in time"
        assert job.state == "exited"
        assert job.returncode == 0
        assert b"hello" in bytes(job.tail)

    async def test_nonzero_exit_marked_failed(self):
        msg = await bash_background.ainvoke({"command": "sh -c 'exit 3'"})
        jid = _job_id_from_launch(msg)
        job = bg.get_job_manager().get(jid)
        await _wait_until(lambda: job.state != "running")
        assert job.state == "failed"
        assert job.returncode == 3

    async def test_stderr_is_merged_into_stdout(self):
        msg = await bash_background.ainvoke(
            {"command": "sh -c 'echo OUT; echo ERR 1>&2'"}
        )
        jid = _job_id_from_launch(msg)
        job = bg.get_job_manager().get(jid)
        await _wait_until(lambda: job.state != "running")
        combined = bytes(job.tail)
        assert b"OUT" in combined
        assert b"ERR" in combined

    async def test_log_file_written_to_disk(self):
        msg = await bash_background.ainvoke({"command": "echo persisted"})
        jid = _job_id_from_launch(msg)
        job = bg.get_job_manager().get(jid)
        await _wait_until(lambda: job.state != "running")
        assert job.log_path.exists()
        assert b"persisted" in job.log_path.read_bytes()


# ---------------------------------------------------------------------------
# Non-blocking guarantee
# ---------------------------------------------------------------------------


class TestNonBlocking:
    async def test_launch_returns_before_command_finishes(self):
        loop = asyncio.get_event_loop()
        t0 = loop.time()
        msg = await bash_background.ainvoke({"command": "sleep 1"})
        elapsed = loop.time() - t0
        assert elapsed < 0.5, f"bash_background blocked for {elapsed:.2f}s"
        jid = _job_id_from_launch(msg)
        job = bg.get_job_manager().get(jid)
        assert job.state == "running"

    async def test_can_do_other_work_while_job_runs(self):
        msg = await bash_background.ainvoke(
            {"command": "for i in 1 2 3; do echo line$i; sleep 0.3; done"}
        )
        jid = _job_id_from_launch(msg)
        # Do unrelated work concurrently.
        counter = 0
        for _ in range(5):
            counter += 1
            await asyncio.sleep(0.05)
        assert counter == 5
        # Job still running (or just finished) and we never blocked on it.
        job = bg.get_job_manager().get(jid)
        await _wait_until(lambda: job.state != "running", timeout=3.0)
        assert job.state == "exited"


# ---------------------------------------------------------------------------
# Status tool
# ---------------------------------------------------------------------------


class TestStatus:
    async def test_status_empty(self):
        out = await bash_status.ainvoke({})
        assert "No background jobs" in out

    async def test_status_lists_all_jobs_newest_first(self):
        m1 = await bash_background.ainvoke({"command": "echo a"})
        await asyncio.sleep(0.05)
        m2 = await bash_background.ainvoke({"command": "echo b"})
        jid1 = _job_id_from_launch(m1)
        jid2 = _job_id_from_launch(m2)

        out = await bash_status.ainvoke({})
        assert jid1 in out
        assert jid2 in out
        # Newest first → jid2 should appear before jid1.
        assert out.index(jid2) < out.index(jid1)

    async def test_status_for_specific_job(self):
        msg = await bash_background.ainvoke({"command": "echo specific"})
        jid = _job_id_from_launch(msg)
        job = bg.get_job_manager().get(jid)
        await _wait_until(lambda: job.state != "running")

        out = await bash_status.ainvoke({"job_id": jid})
        assert f"job_id:      {jid}" in out
        assert "state:       exited" in out
        assert "returncode:  0" in out
        assert "specific" in out  # in recent-output preview

    async def test_status_unknown_job_id(self):
        out = await bash_status.ainvoke({"job_id": "bg_nope"})
        assert "unknown job_id" in out


# ---------------------------------------------------------------------------
# Output tool
# ---------------------------------------------------------------------------


class TestOutput:
    async def test_output_returns_full_capture(self):
        msg = await bash_background.ainvoke({"command": "echo hello world"})
        jid = _job_id_from_launch(msg)
        job = bg.get_job_manager().get(jid)
        await _wait_until(lambda: job.state != "running")
        out = await bash_output.ainvoke({"job_id": jid})
        assert "hello world" in out
        # Header line includes state + rc.
        assert jid in out.splitlines()[0]
        assert "rc=0" in out.splitlines()[0]

    async def test_output_unknown_job(self):
        out = await bash_output.ainvoke({"job_id": "bg_missing"})
        assert "unknown job_id" in out

    async def test_output_tail_limits_lines(self):
        msg = await bash_background.ainvoke(
            {"command": "for i in 1 2 3 4 5; do echo line$i; done"}
        )
        jid = _job_id_from_launch(msg)
        job = bg.get_job_manager().get(jid)
        await _wait_until(lambda: job.state != "running")

        out = await bash_output.ainvoke({"job_id": jid, "tail": 2})
        # Header + last 2 lines.
        body_lines = [l for l in out.splitlines()[1:] if l.strip()]
        assert body_lines == ["line4", "line5"]

    async def test_output_since_byte_incremental(self):
        msg = await bash_background.ainvoke(
            {"command": "for i in 1 2 3; do echo chunk$i; done"}
        )
        jid = _job_id_from_launch(msg)
        job = bg.get_job_manager().get(jid)
        await _wait_until(lambda: job.state != "running")

        # First read from byte 0 — should see everything.
        first = await bash_output.ainvoke({"job_id": jid, "since_byte": 0})
        assert "chunk1" in first
        assert "chunk3" in first

        # Read from the end — should get no new bytes.
        second = await bash_output.ainvoke(
            {"job_id": jid, "since_byte": job.bytes_written}
        )
        # Body after header should be empty / "(no output)".
        assert "(no output)" in second

    async def test_output_no_output_message(self):
        msg = await bash_background.ainvoke({"command": "true"})
        jid = _job_id_from_launch(msg)
        job = bg.get_job_manager().get(jid)
        await _wait_until(lambda: job.state != "running")
        out = await bash_output.ainvoke({"job_id": jid})
        assert "(no output)" in out


# ---------------------------------------------------------------------------
# Kill / timeout
# ---------------------------------------------------------------------------


class TestKillAndTimeout:
    async def test_kill_running_job(self):
        msg = await bash_background.ainvoke({"command": "sleep 30"})
        jid = _job_id_from_launch(msg)
        job = bg.get_job_manager().get(jid)
        await asyncio.sleep(0.1)
        assert job.state == "running"

        result = await bash_kill.ainvoke({"job_id": jid})
        assert "killed" in result.lower()
        await _wait_until(lambda: job.state != "running")
        assert job.state == "killed"
        assert job.returncode is not None and job.returncode < 0

    async def test_kill_unknown_job(self):
        out = await bash_kill.ainvoke({"job_id": "bg_ghost"})
        assert "unknown job_id" in out

    async def test_kill_already_finished_job(self):
        msg = await bash_background.ainvoke({"command": "true"})
        jid = _job_id_from_launch(msg)
        job = bg.get_job_manager().get(jid)
        await _wait_until(lambda: job.state != "running")

        out = await bash_kill.ainvoke({"job_id": jid})
        assert "not running" in out

    async def test_kill_terminates_child_processes(self):
        """SIGTERM must reach the whole process group, not just the shell."""
        # Spawn a shell that spawns a nested sleep; killing the shell only
        # would leave the nested sleep orphaned.
        msg = await bash_background.ainvoke(
            {"command": "sh -c 'sleep 30 & wait'"}
        )
        jid = _job_id_from_launch(msg)
        job = bg.get_job_manager().get(jid)
        await asyncio.sleep(0.2)
        await bash_kill.ainvoke({"job_id": jid})
        finished = await _wait_until(lambda: job.state != "running", timeout=4.0)
        assert finished, "process group was not fully terminated"

    async def test_timeout_kills_job(self):
        msg = await bash_background.ainvoke(
            {"command": "sleep 10", "timeout": 1}
        )
        jid = _job_id_from_launch(msg)
        job = bg.get_job_manager().get(jid)
        finished = await _wait_until(
            lambda: job.state != "running", timeout=4.0
        )
        assert finished
        assert job.state == "timed_out"

    async def test_no_timeout_means_no_kill(self):
        msg = await bash_background.ainvoke({"command": "sleep 0.3"})
        jid = _job_id_from_launch(msg)
        job = bg.get_job_manager().get(jid)
        await _wait_until(lambda: job.state != "running")
        assert job.state == "exited"


# ---------------------------------------------------------------------------
# Safety gates
# ---------------------------------------------------------------------------


class TestSafetyGates:
    async def test_empty_command_rejected(self):
        out = await bash_background.ainvoke({"command": "   "})
        assert out.startswith("Error")
        assert "empty" in out.lower()

    async def test_sandbox_blocks_dangerous_command(self):
        settings = get_settings()
        settings.safety.sandbox_commands = True
        try:
            out = await bash_background.ainvoke({"command": "rm -rf /"})
            assert out.startswith("Error: Command blocked")
        finally:
            settings.safety.sandbox_commands = False


# ---------------------------------------------------------------------------
# Tail buffer behavior
# ---------------------------------------------------------------------------


class TestTailBuffer:
    async def test_tail_buffer_is_bounded(self, monkeypatch):
        # Shrink the cap so we don't have to generate 256 KB.
        monkeypatch.setattr(bg, "TAIL_BUFFER_BYTES", 256)
        msg = await bash_background.ainvoke(
            # Produce ~2 KB of output.
            {"command": "for i in $(seq 1 100); do echo aaaaaaaaaaaaaaaaaaaa; done"}
        )
        jid = _job_id_from_launch(msg)
        job = bg.get_job_manager().get(jid)
        await _wait_until(lambda: job.state != "running")
        assert job.bytes_written > 256
        # In-memory tail must stay bounded.
        assert len(job.tail) <= 256
        # But the full output is on disk.
        assert len(job.log_path.read_bytes()) == job.bytes_written


# ---------------------------------------------------------------------------
# Manager unit checks
# ---------------------------------------------------------------------------


class TestJobManager:
    async def test_new_id_format(self):
        jid = JobManager._new_id()
        assert jid.startswith("bg_")
        assert len(jid) == len("bg_") + 6

    async def test_shutdown_terminates_running_jobs(self):
        mgr = bg.get_job_manager()
        await mgr.launch("sleep 30", timeout=None)
        await mgr.launch("sleep 30", timeout=None)
        running = [j for j in mgr.all() if j.state == "running"]
        assert len(running) == 2

        await mgr.shutdown()
        for job in running:
            await _wait_until(lambda j=job: j.process.returncode is not None)
        assert all(j.state != "running" for j in mgr.all())


# ---------------------------------------------------------------------------
# bash_wait
# ---------------------------------------------------------------------------


class TestBashWait:
    async def test_wait_blocks_until_finished(self):
        loop = asyncio.get_event_loop()
        msg = await bash_background.ainvoke({"command": "sleep 0.5"})
        jid = _job_id_from_launch(msg)

        t0 = loop.time()
        out = await bash_wait.ainvoke({"job_id": jid})
        elapsed = loop.time() - t0

        # Should have actually waited (not returned instantly).
        assert elapsed >= 0.4, f"wait returned too fast: {elapsed:.2f}s"
        # Job is finished and result has status block.
        assert "state:       exited" in out
        assert "returncode:  0" in out
        # No "still running" hint.
        assert "still running" not in out

    async def test_wait_returns_immediately_for_finished_job(self):
        msg = await bash_background.ainvoke({"command": "echo done"})
        jid = _job_id_from_launch(msg)
        job = bg.get_job_manager().get(jid)
        await _wait_until(lambda: job.state != "running")

        loop = asyncio.get_event_loop()
        t0 = loop.time()
        out = await bash_wait.ainvoke({"job_id": jid})
        elapsed = loop.time() - t0

        assert elapsed < 0.2
        assert "state:       exited" in out

    async def test_wait_timeout_returns_running_status(self):
        msg = await bash_background.ainvoke({"command": "sleep 5"})
        jid = _job_id_from_launch(msg)

        out = await bash_wait.ainvoke({"job_id": jid, "timeout": 0.3})
        assert "state:       running" in out
        assert "still running after" in out.lower()
        assert "bash_wait" in out  # hint mentions the tool

        # Job is still alive afterwards; clean up.
        await bash_kill.ainvoke({"job_id": jid})

    async def test_wait_unknown_job(self):
        out = await bash_wait.ainvoke({"job_id": "bg_missing"})
        assert "unknown job_id" in out

    async def test_wait_returns_when_job_is_killed_externally(self):
        msg = await bash_background.ainvoke({"command": "sleep 30"})
        jid = _job_id_from_launch(msg)

        async def _kill_soon():
            await asyncio.sleep(0.2)
            await bash_kill.ainvoke({"job_id": jid})

        kill_task = asyncio.create_task(_kill_soon())
        out = await bash_wait.ainvoke({"job_id": jid, "timeout": 5.0})
        await kill_task

        assert "state:       killed" in out
        assert "still running" not in out

    async def test_wait_picks_up_failed_state(self):
        msg = await bash_background.ainvoke({"command": "sh -c 'exit 2'"})
        jid = _job_id_from_launch(msg)

        out = await bash_wait.ainvoke({"job_id": jid, "timeout": 3.0})
        assert "state:       failed" in out
        assert "returncode:  2" in out


# ---------------------------------------------------------------------------
# Named jobs
# ---------------------------------------------------------------------------


class TestNamedJobs:
    async def test_launch_with_name_stores_and_displays_it(self):
        msg = await bash_background.ainvoke(
            {"command": "echo hi", "name": "greeter"}
        )
        assert "(greeter)" in msg.splitlines()[0]
        jid = _job_id_from_launch(msg)
        job = bg.get_job_manager().get(jid)
        assert job is not None
        assert job.name == "greeter"

    async def test_status_list_includes_name(self):
        await bash_background.ainvoke({"command": "echo a", "name": "alpha"})
        await asyncio.sleep(0.05)
        await bash_background.ainvoke({"command": "echo b"})  # unnamed -> command fallback

        out = await bash_status.ainvoke({})
        assert '"alpha"' in out
        assert '"echo b"' in out  # command used as default name

    async def test_status_detail_shows_name_field(self):
        msg = await bash_background.ainvoke(
            {"command": "echo named", "name": "demo job"}
        )
        job = bg.get_job_manager().all()[0]
        await _wait_until(lambda: job.state != "running")
        out = await bash_status.ainvoke({"job_id": job.id})
        assert "name:        demo job" in out

    async def test_status_detail_falls_back_to_command_name(self):
        await bash_background.ainvoke({"command": "echo plain"})
        job = bg.get_job_manager().all()[0]
        await _wait_until(lambda: job.state != "running")
        out = await bash_status.ainvoke({"job_id": job.id})
        assert "name:        echo plain" in out

    async def test_output_header_includes_name(self):
        await bash_background.ainvoke(
            {"command": "echo x", "name": "tagged"}
        )
        job = bg.get_job_manager().all()[0]
        await _wait_until(lambda: job.state != "running")
        out = await bash_output.ainvoke({"job_id": job.id})
        # Header is the first line, format: [bg_xxxx "tagged" exited, ...]
        header = out.splitlines()[0]
        assert '"tagged"' in header
        assert job.id in header

    async def test_name_is_sanitized(self):
        # Whitespace collapsed, trimmed.
        await bash_background.ainvoke(
            {"command": "echo y", "name": "   spaced    out   "}
        )
        job = bg.get_job_manager().all()[0]
        assert job.name == "spaced out"

    async def test_long_name_truncated(self):
        long_name = "x" * 200
        await bash_background.ainvoke(
            {"command": "echo z", "name": long_name}
        )
        job = bg.get_job_manager().all()[0]
        assert len(job.name) == 60
        assert job.name.endswith("...")

    async def test_empty_name_falls_back_to_command(self):
        await bash_background.ainvoke({"command": "echo q", "name": "   "})
        job = bg.get_job_manager().all()[0]
        assert job.name == "echo q"

    async def test_tracking_uses_id_not_name(self):
        # Two jobs with the same name should both be addressable by id.
        m1 = await bash_background.ainvoke(
            {"command": "echo one", "name": "twin"}
        )
        m2 = await bash_background.ainvoke(
            {"command": "echo two", "name": "twin"}
        )
        jid1 = _job_id_from_launch(m1)
        jid2 = _job_id_from_launch(m2)
        assert jid1 != jid2
        assert bg.get_job_manager().get(jid1).command == "echo one"
        assert bg.get_job_manager().get(jid2).command == "echo two"
