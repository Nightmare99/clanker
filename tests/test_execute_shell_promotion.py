"""Tests for execute_shell auto-promotion to background jobs."""

from __future__ import annotations

import asyncio
import time

import pytest

from clanker.config import get_settings
from clanker.tools import background as bg
from clanker.tools.bash_tools import execute_shell


@pytest.fixture(autouse=True)
def _disable_safety():
    settings = get_settings()
    prev_sandbox = settings.safety.sandbox_commands
    prev_confirm = settings.safety.require_confirmation
    prev_promote = settings.safety.foreground_promote_after_seconds
    prev_timeout = settings.safety.command_timeout
    settings.safety.sandbox_commands = False
    settings.safety.require_confirmation = False
    yield
    settings.safety.sandbox_commands = prev_sandbox
    settings.safety.require_confirmation = prev_confirm
    settings.safety.foreground_promote_after_seconds = prev_promote
    settings.safety.command_timeout = prev_timeout


@pytest.fixture(autouse=True)
def _fresh_manager(monkeypatch, tmp_path):
    monkeypatch.setattr(bg, "_JOB_LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(bg, "_manager", None)
    yield


async def _wait_until(predicate, *, timeout: float = 5.0, interval: float = 0.05):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


class TestFastCommandsStillReturnOutput:
    def test_quick_command_returns_output_directly(self):
        settings = get_settings()
        settings.safety.foreground_promote_after_seconds = 5
        out = execute_shell.invoke({"command": "echo hello"})
        assert "hello" in out
        assert "promoted" not in out.lower()

    def test_quick_nonzero_exit_reports_returncode(self):
        settings = get_settings()
        settings.safety.foreground_promote_after_seconds = 5
        out = execute_shell.invoke({"command": "sh -c 'echo oops; exit 7'"})
        assert "exited with code 7" in out
        assert "oops" in out

    def test_stderr_merged_into_foreground_output(self):
        settings = get_settings()
        settings.safety.foreground_promote_after_seconds = 5
        out = execute_shell.invoke(
            {"command": "sh -c 'echo OUT; echo ERR 1>&2'"}
        )
        assert "OUT" in out
        assert "ERR" in out


class TestAutoPromotion:
    def test_slow_command_is_promoted(self):
        settings = get_settings()
        settings.safety.foreground_promote_after_seconds = 1
        settings.safety.command_timeout = 60_000

        t0 = time.time()
        out = execute_shell.invoke({"command": "sleep 5"})
        elapsed = time.time() - t0

        # Returned shortly after the 1s promotion threshold, NOT after 5s.
        assert elapsed < 3.0, f"execute_shell blocked for {elapsed:.2f}s"
        assert "promoted to bg_" in out.lower()

        # Extract job id from the message and verify it's registered + running.
        jid = next(tok for tok in out.split() if tok.startswith("bg_")).rstrip(".")
        # Strip trailing punctuation if any.
        jid = jid.split("'")[0] if "'" in jid else jid
        job = bg.get_job_manager().get(jid)
        assert job is not None
        assert job.state == "running"

        # The promoted job eventually finishes on its own.
        ok = asyncio.run(_wait_for_job(job, timeout=8.0))
        assert ok
        assert job.state == "exited"
        assert job.returncode == 0

    def test_promoted_job_preserves_already_captured_output(self):
        settings = get_settings()
        settings.safety.foreground_promote_after_seconds = 1
        settings.safety.command_timeout = 60_000

        # Emit a line in the first 1s window, then keep going past promotion.
        out = execute_shell.invoke(
            {"command": "sh -c 'echo EARLY; sleep 3; echo LATE'"}
        )
        assert "promoted" in out.lower()
        jid = _extract_job_id(out)
        job = bg.get_job_manager().get(jid)
        assert job is not None

        # Pre-promotion output is already in the tail buffer + log.
        assert b"EARLY" in bytes(job.tail)
        assert b"EARLY" in job.log_path.read_bytes()

        # Drainer keeps running — late output also lands.
        ok = asyncio.run(_wait_for_job(job, timeout=8.0))
        assert ok
        assert b"LATE" in job.log_path.read_bytes()

    def test_promotion_disabled_with_zero_threshold(self):
        settings = get_settings()
        settings.safety.foreground_promote_after_seconds = 0
        settings.safety.command_timeout = 60_000

        t0 = time.time()
        out = execute_shell.invoke({"command": "sleep 1"})
        elapsed = time.time() - t0

        # No promotion — we actually waited for the full sleep.
        assert elapsed >= 0.9
        assert "promoted" not in out.lower()

    def test_hard_timeout_when_timeout_smaller_than_promote_threshold(self):
        settings = get_settings()
        settings.safety.foreground_promote_after_seconds = 30

        out = execute_shell.invoke({"command": "sleep 10", "timeout": 1})
        assert "timed out" in out.lower()
        # No background job was created.
        assert all("sleep 10" not in j.command for j in bg.get_job_manager().all())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_job_id(text: str) -> str:
    for tok in text.replace("\n", " ").split():
        if tok.startswith("bg_"):
            # Strip surrounding punctuation like trailing '.' or "'..."
            return "".join(c for c in tok if c.isalnum() or c == "_")
    raise AssertionError(f"No job id found in: {text!r}")


async def _wait_for_job(job, timeout: float = 5.0) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if job.state != "running":
            return True
        await asyncio.sleep(0.05)
    return False
