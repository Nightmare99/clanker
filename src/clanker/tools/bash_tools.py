"""Bash command execution tools."""

import asyncio
import contextlib
import os
import signal
import subprocess
import time

from langchain.tools import tool

from clanker.config import get_effective_blacklist, get_settings
from clanker.logging import get_logger
from clanker.runtime import is_yolo_mode
from clanker.utils.sandbox import is_command_safe

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


# Approval menu option labels.
_APPROVE_YES = "Yes, execute"
_APPROVE_ALWAYS = "Yes, and don't ask again (this session)"
_APPROVE_NO = "No, reject and stop"

# Module-level approval prompter set by the streaming layer, mirroring the
# notify/ask callbacks. Signature: (question, options, preface) -> dict with
# {"selected": [...], "cancelled": bool}. When None, a plain stdin prompt is used.
_approval_callback = None


def set_approval_callback(callback) -> None:
    """Register the interactive approval prompter.

    Called by the streaming layer before graph execution so the bash approval
    gate can use the same arrow-key menu as ask_user (with spinner coordination).
    Pass None to clear it (falls back to a plain numbered stdin prompt).
    """
    global _approval_callback
    _approval_callback = callback


def get_approval_callback():
    """Return the currently registered approval callback."""
    return _approval_callback


def _format_command_box(command: str) -> str:
    """Build a plain-text framed box showing the command (menu preface)."""
    width = 61
    lines = ["  Bash Command"]
    cmd_width = width - 4
    display = command if len(command) <= cmd_width else None
    if display is not None:
        lines.append(f"  $ {command}")
    else:
        # Wrap long commands across lines.
        lines.append(f"  $ {command[:cmd_width]}")
        remaining = command[cmd_width:]
        while remaining:
            lines.append(f"    {remaining[:cmd_width]}")
            remaining = remaining[cmd_width:]
    return "\n".join(lines)


def prompt_for_approval(command: str) -> bool:
    """Prompt the user to approve a bash command via an arrow-key menu.

    Presents three choices: execute, execute + stop asking this session
    (enables yolo mode), or reject. Uses the registered approval callback (the
    themed arrow-key menu with spinner coordination) when available, else a
    plain numbered stdin prompt.

    Returns:
        True if approved.

    Raises:
        CommandRejectedError: If the user rejects or cancels.
    """
    preface = _format_command_box(command)
    options = [_APPROVE_YES, _APPROVE_ALWAYS, _APPROVE_NO]

    callback = _approval_callback
    try:
        if callback is not None:
            result = callback("Run this command?", options, preface=preface)
        else:
            result = _approval_fallback(preface, options)
    except (EOFError, KeyboardInterrupt):
        raise CommandRejectedError("Command cancelled") from None
    except Exception as exc:  # noqa: BLE001 - a UI failure must reject, not crash
        logger.warning("Approval prompt failed: %s", exc)
        raise CommandRejectedError("Approval prompt failed") from None

    selected = result.get("selected") or []
    cancelled = bool(result.get("cancelled", False)) or not selected
    choice = selected[0] if selected else None

    if cancelled or choice == _APPROVE_NO:
        raise CommandRejectedError("User rejected the command")

    if choice == _APPROVE_ALWAYS:
        # Stop prompting for the rest of this session.
        from clanker.runtime import set_yolo_mode

        set_yolo_mode(True)
        logger.info("User enabled auto-approve (yolo) for this session")
        return True

    # Default / _APPROVE_YES
    return True


def _approval_fallback(preface: str, options: list[str]) -> dict:
    """Numbered-list approval prompt for non-interactive / piped stdin."""
    print()
    print(preface)
    for i, label in enumerate(options, 1):
        print(f"    {i}) {label}")
    try:
        raw = input("  Enter choice [1-3]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return {"selected": [], "cancelled": True}
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return {"selected": [options[int(raw) - 1]], "cancelled": False}
    # Anything else (blank, 0, out of range) counts as reject.
    return {"selected": [], "cancelled": True}


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
        # The effective blacklist is the union of the system-wide setting and
        # the project's .clanker/blacklist (resolved from the current cwd, which
        # is the project root for execute_shell).
        extra_blacklist = get_effective_blacklist()
        is_safe, reason = is_command_safe(command, extra_blacklist)
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
    except TimeoutError:
        # Hit promotion threshold but process is still alive.
        if promote_after < timeout_seconds:
            # We're already on the JobManager's loop — use the internal
            # coroutine directly to avoid a re-submit deadlock.
            drain_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await drain_task
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
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            await process.wait()
        drain_task.cancel()
        return f"Error: Command timed out after {timeout_seconds} seconds"

    # Process completed within the soft deadline; let the drainer finish.
    with contextlib.suppress(asyncio.CancelledError):
        await drain_task

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

    except TimeoutError:
        return f"Error: Command timed out after {timeout_seconds} seconds"
    except OSError as e:
        return f"Error executing command: {e}"
