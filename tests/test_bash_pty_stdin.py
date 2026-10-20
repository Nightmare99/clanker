"""Tests for bash stdin input and PTY support."""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import patch

import pytest

from clanker.tools.background import (
    bash_input,
    get_job_manager,
)
from clanker.tools.bash_tools import execute_shell


class TestExecuteShellStdinAndPty:
    @patch("clanker.tools.bash_tools.is_yolo_mode", return_value=True)
    def test_execute_shell_with_input(self, mock_yolo) -> None:
        cmd = f"{sys.executable} -c \"import sys; line = sys.stdin.readline().strip(); print('received:', line)\""
        res = execute_shell.invoke({"command": cmd, "input": "hello_clanker\n"})
        assert "received: hello_clanker" in res

    @pytest.mark.skipif(os.name == "nt", reason="PTY is POSIX-only")
    @patch("clanker.tools.bash_tools.is_yolo_mode", return_value=True)
    def test_execute_shell_pty_mode(self, mock_yolo) -> None:
        cmd = f"{sys.executable} -c \"import sys; print('isatty:', sys.stdout.isatty())\""
        # Without PTY: isatty is False
        res_no_pty = execute_shell.invoke({"command": cmd, "pty": False})
        assert "isatty: False" in res_no_pty

        # With PTY: isatty is True
        res_pty = execute_shell.invoke({"command": cmd, "pty": True})
        assert "isatty: True" in res_pty

    @pytest.mark.skipif(os.name == "nt", reason="PTY is POSIX-only")
    @patch("clanker.tools.bash_tools.is_yolo_mode", return_value=True)
    def test_execute_shell_pty_with_input(self, mock_yolo) -> None:
        cmd = f"{sys.executable} -c \"import sys; text = input('prompt> '); print('echo:', text)\""
        res = execute_shell.invoke({"command": cmd, "input": "typed_input\n", "pty": True})
        assert "echo: typed_input" in res


class TestBackgroundBashInput:
    @patch("clanker.tools.background.run_safety_checks", return_value=None)
    @pytest.mark.asyncio
    async def test_bash_input_writes_to_background_process(self, mock_safety) -> None:
        mgr = get_job_manager()
        # Launch a background script that waits on stdin
        cmd = f"{sys.executable} -u -c \"import sys; sys.stdout.write('ready\\n'); sys.stdout.flush(); line = sys.stdin.readline(); sys.stdout.write('got:' + line); sys.stdout.flush()\""
        job = await mgr.launch(cmd, timeout=30, name="stdin_test")

        # Wait until process writes "ready"
        for _ in range(50):
            if b"ready" in job.tail:
                break
            await asyncio.sleep(0.05)
        assert b"ready" in job.tail

        # Send input via bash_input
        res = bash_input.invoke({"job_id": job.id, "text": "dynamic_answer"})
        assert res["ok"] is True
        assert res["job_id"] == job.id

        # Wait for the process to exit after receiving input
        for _ in range(50):
            if job.state != "running":
                break
            await asyncio.sleep(0.05)

        assert b"got:dynamic_answer" in job.tail

    def test_bash_input_unknown_job(self) -> None:
        res = bash_input.invoke({"job_id": "bg_nonexistent_xyz", "text": "test"})
        assert res["ok"] is False
        assert "unknown" in res["error"].lower()
