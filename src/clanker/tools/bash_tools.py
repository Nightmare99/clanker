"""Bash command execution tools."""

import asyncio
import os
import shlex
import signal
import subprocess
import time
from typing import Any

from langchain.tools import tool

from clanker.config import get_settings
from clanker.logging import get_logger
from clanker.runtime import is_yolo_mode
from clanker.utils.sandbox import is_command_safe, requires_confirmation

# Module logger
logger = get_logger("tools.bash")


def _get_clean_env() -> dict[str, str]:
    """Get a clean environment for subprocesses.

    Removes PyInstaller-specific variables that can interfere with
    child processes (e.g., SSL issues, library paths).
    """
    env = os.environ.copy()

    # Remove PyInstaller-specific variables
    pyinstaller_vars = [
        "_MEIPASS",
        "_MEIPASS2",
        "LD_LIBRARY_PATH",
        "DYLD_LIBRARY_PATH",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    ]
    for var in pyinstaller_vars:
        env.pop(var, None)

    return env


class CommandRejectedError(Exception):
    """Raised when user rejects a bash command."""
    pass


def prompt_for_approval(command: str) -> bool:
    """Display approval prompt for a bash command.

    Returns:
        True if approved, False if rejected.

    Raises:
        CommandRejectedError: If user rejects or cancels.
    """
    import sys

    # Clear any spinner/loading artifacts and move to new line
    sys.stdout.write("\r\033[K")  # Clear current line
    sys.stdout.flush()

    # Format the prompt nicely
    print()
    print("\033[33m╭─────────────────────────────────────────────────────────────╮\033[0m")
    print("\033[33m│\033[0m  \033[1;33mBash Command\033[0m                                               \033[33m│\033[0m")
    print("\033[33m├─────────────────────────────────────────────────────────────┤\033[0m")

    # Display command with wrapping
    cmd_width = 57
    if len(command) <= cmd_width:
        print(f"\033[33m│\033[0m  \033[36m$\033[0m {command}")
    else:
        # First line
        print(f"\033[33m│\033[0m  \033[36m$\033[0m {command[:cmd_width]}")
        # Wrap remaining
        remaining = command[cmd_width:]
        while remaining:
            chunk = remaining[:cmd_width]
            remaining = remaining[cmd_width:]
            print(f"\033[33m│\033[0m    {chunk}")

    print("\033[33m├─────────────────────────────────────────────────────────────┤\033[0m")
    print("\033[33m│\033[0m  [\033[32my\033[0m]es  execute     [\033[31mN\033[0m]o  reject and stop                   \033[33m│\033[0m")
    print("\033[33m╰─────────────────────────────────────────────────────────────╯\033[0m")

    try:
        response = input("\033[33mApprove?\033[0m ").strip().lower()
        if response in ("y", "yes"):
            return True
        else:
            raise CommandRejectedError("User rejected the command")
    except (EOFError, KeyboardInterrupt):
        print()
        raise CommandRejectedError("Command cancelled")

# Maximum output size to prevent memory issues
MAX_OUTPUT_SIZE = 100_000  # 100KB


def run_safety_checks(command: str) -> str | None:
    """Run sandbox + approval gates shared across bash tools.

    Returns an error string if the command is blocked, or None if it
    passed all gates. Raises CommandRejectedError if the user rejects
    the interactive approval prompt.
    """
    if not command or not command.strip():
        return "Error: Command cannot be empty"

    settings = get_settings()

    if settings.safety.sandbox_commands:
        is_safe, reason = is_command_safe(command)
        if not is_safe:
            logger.warning("Command blocked: %s - %s", command[:50], reason)
            return f"Error: Command blocked - {reason}"

    if not is_yolo_mode() and settings.safety.require_confirmation:
        prompt_for_approval(command)  # Raises CommandRejectedError if rejected

    return None


@tool
def execute_shell(command: str, timeout: int | None = None) -> str:
    """Execute a bash command and return the output.

    Blocking commands that exceed `safety.foreground_promote_after_seconds`
    are auto-promoted to a background job: this call returns immediately
    with a job id, the command keeps running, and the agent can poll
    progress with `bash_status` / `bash_output` (or stop it with
    `bash_kill`). Set the threshold to 0 in config to disable promotion.

    Args:
        command: The bash command to execute.
        timeout: Optional hard timeout in seconds. Defaults to
            `safety.command_timeout`. Applied to the foreground wait;
            after auto-promotion, the job has no timeout (use `bash_kill`).

    Returns:
        Command output (stdout and stderr combined), an auto-promotion
        notice with a job id, or an error message.
    """
    logger.info(
        "Executing bash command: %s",
        command[:100] + "..." if len(command) > 100 else command,
    )

    blocked = run_safety_checks(command)
    if blocked is not None:
        return blocked

    settings = get_settings()
    timeout_seconds = timeout or (settings.safety.command_timeout // 1000)
    promote_after = settings.safety.foreground_promote_after_seconds

    # If promotion is disabled, keep the simple blocking path.
    if promote_after <= 0:
        return _run_foreground_blocking(command, timeout_seconds)

    # Run the subprocess on the JobManager's dedicated loop so that, if
    # we hit the promotion threshold, the live process and its streams
    # are already bound to the loop that will own them long-term.
    from clanker.tools.background import get_job_manager

    mgr = get_job_manager()
    try:
        return mgr.run(
            _run_foreground_with_promotion(
                command=command,
                timeout_seconds=timeout_seconds,
                promote_after=promote_after,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("execute_shell promotion path crashed: %s", exc)
        return f"Error: {type(exc).__name__}: {exc}"


def _run_foreground_blocking(command: str, timeout_seconds: int) -> str:
    """Simple subprocess.run path used when promotion is disabled."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=None,
            env=_get_clean_env(),
        )

        output_parts: list[str] = []
        if result.stdout:
            stdout = result.stdout
            if len(stdout) > MAX_OUTPUT_SIZE:
                stdout = stdout[:MAX_OUTPUT_SIZE] + "\n... (output truncated)"
            output_parts.append(stdout)
        if result.stderr:
            stderr = result.stderr
            if len(stderr) > MAX_OUTPUT_SIZE:
                stderr = stderr[:MAX_OUTPUT_SIZE] + "\n... (stderr truncated)"
            if output_parts:
                output_parts.append(f"\n[stderr]\n{stderr}")
            else:
                output_parts.append(stderr)

        output = "".join(output_parts).strip()

        if result.returncode != 0:
            logger.warning(
                "Command exited with code %d: %s", result.returncode, command[:50]
            )
            return f"Command exited with code {result.returncode}\n{output}"

        return output if output else "(no output)"

    except subprocess.TimeoutExpired:
        logger.error(
            "Command timed out after %d seconds: %s", timeout_seconds, command[:50]
        )
        return f"Error: Command timed out after {timeout_seconds} seconds"
    except OSError as e:
        logger.error("Error executing command: %s", e)
        return f"Error executing command: {e}"
    except Exception as e:  # noqa: BLE001
        logger.exception("Unexpected error executing command: %s", e)
        return f"Error: {type(e).__name__}: {e}"


async def _run_foreground_with_promotion(
    command: str,
    timeout_seconds: int,
    promote_after: int,
) -> str:
    """Run a command in the foreground, auto-promoting to background if slow.

    Streams stdout (with stderr merged) into an in-memory buffer. If the
    process is still running after `promote_after` seconds, hands the
    live process + captured output to the JobManager and returns a
    promotion notice with the new job id.
    """
    # Imported here to avoid a circular import at module load time.
    from clanker.tools.background import get_job_manager

    started = time.time()
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=_get_clean_env(),
        start_new_session=True,
    )

    buffer = bytearray()

    async def _drain() -> None:
        assert process.stdout is not None
        while True:
            chunk = await process.stdout.read(4096)
            if not chunk:
                break
            buffer.extend(chunk)

    drain_task = asyncio.create_task(_drain())

    # Whichever fires first wins: process exit OR promotion deadline.
    soft_deadline = min(promote_after, timeout_seconds)
    try:
        await asyncio.wait_for(process.wait(), timeout=soft_deadline)
    except asyncio.TimeoutError:
        # Hit promotion threshold but process is still alive.
        if promote_after < timeout_seconds:
            # We're already on the JobManager's loop — use the internal
            # coroutine directly to avoid a re-submit deadlock.
            drain_task.cancel()
            try:
                await drain_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            mgr = get_job_manager()
            job = await mgr._adopt_coro(
                command=command,
                process=process,
                started_at=started,
                captured=bytes(buffer),
            )
            return (
                f"Command still running after {promote_after}s — promoted to "
                f"{job.id}.\n"
                f"Use bash_status('{job.id}') / bash_output('{job.id}') to "
                f"check progress, or bash_kill('{job.id}') to stop it."
            )
        # Otherwise, promote_after >= timeout_seconds: this is a hard timeout.
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            await process.wait()
        drain_task.cancel()
        return f"Error: Command timed out after {timeout_seconds} seconds"

    # Process completed within the soft deadline; let the drainer finish.
    try:
        await drain_task
    except asyncio.CancelledError:
        pass

    output = bytes(buffer).decode("utf-8", errors="replace")
    if len(output) > MAX_OUTPUT_SIZE:
        output = output[:MAX_OUTPUT_SIZE] + "\n... (output truncated)"
    output = output.strip()

    rc = process.returncode
    if rc != 0:
        logger.warning("Command exited with code %s: %s", rc, command[:50])
        return f"Command exited with code {rc}\n{output}"
    return output if output else "(no output)"



async def bash_async(command: str, timeout: int | None = None) -> str:
    """Execute a bash command asynchronously.

    Args:
        command: The bash command to execute.
        timeout: Optional timeout in seconds.

    Returns:
        Command output or error message.
    """
    blocked = run_safety_checks(command)
    if blocked is not None:
        return blocked

    settings = get_settings()

    timeout_seconds = timeout or (settings.safety.command_timeout // 1000)

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_get_clean_env(),
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds,
        )

        output_parts = []

        if stdout:
            stdout_str = stdout.decode("utf-8", errors="replace")
            if len(stdout_str) > MAX_OUTPUT_SIZE:
                stdout_str = stdout_str[:MAX_OUTPUT_SIZE] + "\n... (output truncated)"
            output_parts.append(stdout_str)

        if stderr:
            stderr_str = stderr.decode("utf-8", errors="replace")
            if len(stderr_str) > MAX_OUTPUT_SIZE:
                stderr_str = stderr_str[:MAX_OUTPUT_SIZE] + "\n... (stderr truncated)"
            if output_parts:
                output_parts.append(f"\n[stderr]\n{stderr_str}")
            else:
                output_parts.append(stderr_str)

        output = "".join(output_parts).strip()

        if process.returncode != 0:
            return f"Command exited with code {process.returncode}\n{output}"

        return output if output else "(no output)"

    except asyncio.TimeoutError:
        return f"Error: Command timed out after {timeout_seconds} seconds"
    except OSError as e:
        return f"Error executing command: {e}"
