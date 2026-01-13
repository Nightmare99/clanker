"""Bash command execution tools."""

import asyncio
import shlex
import subprocess
from typing import Any

from langchain.tools import tool

from clanker.config import get_settings
from clanker.logging import get_logger
from clanker.utils.sandbox import is_command_safe, requires_confirmation

# Module logger
logger = get_logger("tools.bash")

# Maximum output size to prevent memory issues
MAX_OUTPUT_SIZE = 100_000  # 100KB


@tool
def bash(command: str, timeout: int | None = None) -> str:
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

    # Check if confirmation would be required (for now, just note it)
    if requires_confirmation(command) and settings.safety.require_confirmation:
        # In a real implementation, this would prompt the user
        # For now, we'll allow it but note the risk
        pass

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
