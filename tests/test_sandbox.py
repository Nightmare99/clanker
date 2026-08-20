"""Tests for sandbox utilities."""

import tempfile
from pathlib import Path

from clanker.utils.sandbox import is_command_safe, is_path_safe, requires_confirmation


class TestCommandSafety:
    """Tests for command safety checks."""

    def test_safe_commands(self) -> None:
        """Test that safe commands are allowed."""
        safe_commands = [
            "ls -la",
            "cat file.txt",
            "python script.py",
            "npm install",
            "git status",
            "echo hello",
        ]

        for cmd in safe_commands:
            is_safe, reason = is_command_safe(cmd)
            assert is_safe, f"Command '{cmd}' should be safe, got: {reason}"

    def test_dangerous_commands_blocked(self) -> None:
        """Test that dangerous commands are blocked."""
        dangerous_commands = [
            "rm -rf /",
            "rm -rf /*",
            "> /dev/sda",
            "mkfs.ext4 /dev/sda",
        ]

        for cmd in dangerous_commands:
            is_safe, reason = is_command_safe(cmd)
            assert not is_safe, f"Command '{cmd}' should be blocked"
            assert reason, "Should provide a reason"

    def test_confirmation_required(self) -> None:
        """Test commands that require confirmation."""
        confirmation_commands = [
            "rm file.txt",
            "mv old.txt new.txt",
            "git push origin main",
            "git reset --hard HEAD",
        ]

        for cmd in confirmation_commands:
            assert requires_confirmation(cmd), f"'{cmd}' should require confirmation"

    def test_no_confirmation_needed(self) -> None:
        """Test commands that don't need confirmation."""
        safe_commands = [
            "ls -la",
            "cat file.txt",
            "git status",
            "python --version",
        ]

        for cmd in safe_commands:
            assert not requires_confirmation(cmd), f"'{cmd}' should not need confirmation"


class TestPathSafety:
    """Tests for path safety checks."""

    def test_safe_paths(self) -> None:
        """Test that normal paths are safe."""
        safe_paths = [
            "/home/user/project/file.txt",
            "/tmp/test.txt",
            "./relative/path.py",
            "file.txt",
        ]

        for path in safe_paths:
            is_safe, reason = is_path_safe(path)
            assert is_safe, f"Path '{path}' should be safe, got: {reason}"

    def test_protected_paths_for_write(self) -> None:
        """Test that protected paths are blocked for writes."""
        protected_paths = [
            "/etc/passwd",
            "/bin/bash",
            "/usr/local/bin/python",
            "/",
        ]

        for path in protected_paths:
            is_safe, reason = is_path_safe(path, for_write=True)
            assert not is_safe, f"Path '{path}' should be blocked for write"

    def test_protected_paths_ok_for_read(self) -> None:
        """Test that protected paths are OK for reading."""
        # Reading system files should be allowed
        is_safe, _ = is_path_safe("/etc/hosts", for_write=False)
        assert is_safe

    def test_symlinked_protected_path_still_blocked(self) -> None:
        """Regression: on macOS, /etc (and /bin, /var, ...) are symlinks into
        /private/... -- resolving the input path but comparing it against
        the LITERAL, unresolved protected-path strings let writes silently
        through. Exercise the resolved form directly so this holds
        regardless of which platform runs the test."""
        resolved = str(Path("/etc/passwd").resolve())
        is_safe, reason = is_path_safe(resolved, for_write=True)
        assert not is_safe, f"Resolved protected path '{resolved}' should be blocked"
        assert "protected path" in reason

    def test_system_temp_dir_writable(self) -> None:
        """The OS temp directory must stay writable even though it can
        resolve under a protected prefix (e.g. macOS: $TMPDIR -> /var/folders
        -> /private/var/folders, under the protected "/var" entry) -- lots
        of real functionality (spawn_subagent's truncated-output files,
        pytest's own tmp_path fixture) depends on writing there."""
        temp_file = str(Path(tempfile.gettempdir()) / "clanker_sandbox_test.txt")
        is_safe, reason = is_path_safe(temp_file, for_write=True)
        assert is_safe, f"Temp dir path should be writable, got: {reason}"
