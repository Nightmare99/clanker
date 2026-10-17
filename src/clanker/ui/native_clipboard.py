"""Native clipboard writes for local macOS sessions without OSC 52 support."""

import asyncio
import os
from contextlib import suppress

from clanker.ui import keyboard


def is_local_macos() -> bool:
    # An SSH session must copy to the client through the terminal, not to the
    # remote Mac's pasteboard.
    return keyboard.is_macos() and not any(
        os.environ.get(key) for key in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY")
    )


async def write_text(text: str) -> bool:
    """Write through stdin, with bounded runtime and no clipboard data in argv."""
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            "/usr/bin/pbcopy", stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(process.communicate(text.encode("utf-8")), timeout=2)
        return process.returncode == 0
    except (OSError, TimeoutError):
        return False
    finally:
        if process is not None and process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()
