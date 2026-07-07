"""Notify tool - allows the agent to send status updates to the user mid-execution.

The tool writes directly to the terminal while the agent continues running,
giving the user visibility into long-running operations without waiting for
the final response.

Architecture: A module-level callback is registered by the streaming layer
before graph execution begins (same pattern as runtime.py / yolo mode).
The tool calls the callback synchronously, which prints immediately via Rich.
"""

import sys
from typing import Callable

from langchain_core.tools import tool

from clanker.logging import get_logger

logger = get_logger("tools.notify")

# Module-level output callback set by the streaming layer.
# Signature: (message: str, level: str) -> None
# When None, falls back to plain print().
_output_callback: Callable[[str, str], None] | None = None


def set_notify_callback(callback: Callable[[str, str], None] | None) -> None:
    """Register the output callback for the notify tool.

    Called by the streaming layer before graph execution begins so that
    notify() can write directly to the Rich console mid-stream.

    Args:
        callback: Function that accepts (message, level) and prints to the
                  console, or None to clear the callback.
    """
    global _output_callback
    _output_callback = callback


def get_notify_callback() -> Callable[[str, str], None] | None:
    """Return the currently registered notify callback."""
    return _output_callback


@tool
def notify(message: str, level: str = "info") -> dict:
    """Send an immediate status update or progress message to the user.

    Use this tool liberally and often to keep the user continuously informed
    as you work - narrate what you're doing like a pair-programmer thinking out
    loud. Send a quick update whenever you start a step, switch phases, kick off
    a background job, hit a milestone, or discover something important. The
    message is printed to the terminal RIGHT NOW while the agent continues
    execution; the user does NOT have to wait for the final response to see it.

    Err on the side of sending updates: a steady stream of short status messages
    is far better than leaving the user in silence. When in doubt, notify. The
    only thing to avoid is mechanically narrating every trivial action in a tight
    burst (e.g. one notify per line of a quick edit).

    Messages render as formatted Markdown panels, so use light Markdown: **bold**
    for the key action or noun, and backticks for code, paths, commands, and
    identifiers.

    Good uses:
    - "Scanning **200 files** for test coverage..."
    - "Tests pass — now fixing the **type errors** in `api.py`..."
    - "Found **3 bugs** in `auth.py`, fixing them now..."
    - "`build` succeeded — running integration tests..."

    Args:
        message: The status message to display to the user. Keep it concise
                 (one short sentence). Light Markdown is supported and encouraged
                 (**bold**, `code`); avoid long paragraphs.
        level: Display level - one of: "info" (default, cyan),
               "success" (green), "warning" (yellow), "error" (red).

    Returns:
        Confirmation dict so the agent knows the message was sent.
    """
    valid_levels = ("info", "success", "warning", "error")
    if level not in valid_levels:
        level = "info"

    logger.debug("notify(%s): %s", level, message)

    callback = _output_callback
    if callback is not None:
        try:
            callback(message, level)
        except Exception as exc:
            # Never let a display error break the agent
            logger.warning("notify callback raised: %s", exc)
            _fallback_print(message, level)
    else:
        _fallback_print(message, level)

    return {"ok": True, "sent": True, "message": message, "level": level}


def _fallback_print(message: str, level: str) -> None:
    """Plain-text fallback when no Rich callback is registered."""
    prefix = {
        "info": "[INFO]",
        "success": "[OK]",
        "warning": "[WARN]",
        "error": "[ERR]",
    }.get(level, "[INFO]")
    print(f"\n{prefix} {message}", flush=True)
