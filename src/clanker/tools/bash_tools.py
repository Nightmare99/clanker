"""Bash command execution tools."""

import asyncio
import shlex
import subprocess
from typing import Any

from langchain.tools import tool

from clanker.config import get_settings
from clanker.logging import get_logger
from clanker.runtime import is_yolo_mode
from clanker.utils.sandbox import is_command_safe, requires_confirmation

# Module logger
logger = get_logger("tools.bash")


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


@tool
def run(command: str, timeout: int | None = None) -> str:
    """Execute a bash command and return the output.

    Args:
        command: The bash command to execute.
        timeout: Optional timeout in seconds. Defaults to 120 seconds.

    Returns:
        Command output (stdout and stderr combined) or error message.
    """
    logger.info("Executing bash command: %s", command[:100] + "..." if len(command) > 100 else command)

    if not command or not command.strip():
        logger.warning("Empty command received")
        return "Error: Command cannot be empty"

    settings = get_settings()

    # Security check
    is_safe, reason = is_command_safe(command)
    if not is_safe:
        logger.warning("Command blocked: %s - %s", command[:50], reason)
        return f"Error: Command blocked - {reason}"

    # Command approval (unless in yolo mode)
    if not is_yolo_mode():
        prompt_for_approval(command)  # Raises CommandRejectedError if rejected

    # Set timeout
    timeout_seconds = timeout or (settings.safety.command_timeout // 1000)

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=None,  # Use current directory
        )

        output_parts = []

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
            logger.warning("Command exited with code %d: %s", result.returncode, command[:50])
            return f"Command exited with code {result.returncode}\n{output}"

        logger.debug("Command completed successfully (output: %d bytes)", len(output))
        return output if output else "(no output)"

    except subprocess.TimeoutExpired:
        logger.error("Command timed out after %d seconds: %s", timeout_seconds, command[:50])
        return f"Error: Command timed out after {timeout_seconds} seconds"
    except OSError as e:
        logger.error("Error executing command: %s", e)
        return f"Error executing command: {e}"
    except Exception as e:
        logger.exception("Unexpected error executing command: %s", e)
        return f"Error: {type(e).__name__}: {e}"


async def bash_async(command: str, timeout: int | None = None) -> str:
    """Execute a bash command asynchronously.

    Args:
        command: The bash command to execute.
        timeout: Optional timeout in seconds.

    Returns:
        Command output or error message.
    """
    if not command or not command.strip():
        return "Error: Command cannot be empty"

    settings = get_settings()

    is_safe, reason = is_command_safe(command)
    if not is_safe:
        return f"Error: Command blocked - {reason}"

    # Command approval (unless in yolo mode)
    if not is_yolo_mode():
        prompt_for_approval(command)  # Raises CommandRejectedError if rejected

    timeout_seconds = timeout or (settings.safety.command_timeout // 1000)

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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
