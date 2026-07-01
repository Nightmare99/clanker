"""ask_user tool - lets the agent ask the user a multiple-choice question mid-task.

When the agent hits a genuine fork it can't resolve on its own (which
environment to deploy to, which files to touch, whether to proceed with a
destructive change), it calls ``ask_user`` to pause, present options, and read
the user's pick -- then continues in the same turn.

Architecture mirrors ``notify_tools.py``: the streaming layer registers a
console-backed asker via ``set_ask_callback`` before graph execution. When no
callback is set (or it fails), the tool falls back to :func:`select_options`
directly, which itself degrades to a numbered stdin prompt off-TTY.
"""

from __future__ import annotations

from collections.abc import Callable

from langchain_core.tools import tool

from clanker.logging import get_logger

logger = get_logger("tools.ask")

# Upper bound on options to keep the menu usable.
MAX_OPTIONS = 10

# Module-level asker callback set by the streaming layer.
# Signature: (question, options, multi_select, allow_other, allow_cancel) -> dict
_ask_callback: Callable[..., dict] | None = None


def set_ask_callback(callback: Callable[..., dict] | None) -> None:
    """Register the interactive asker used by ask_user.

    Called by the streaming layer before graph execution so ask_user can drive
    the Rich/prompt_toolkit selector. Pass None to clear it (falls back to a
    plain stdin prompt).
    """
    global _ask_callback
    _ask_callback = callback


def get_ask_callback() -> Callable[..., dict] | None:
    """Return the currently registered asker callback."""
    return _ask_callback


@tool
def ask_user(
    question: str,
    options: list[str],
    multi_select: bool = False,
    allow_other: bool = True,
    allow_cancel: bool = True,
) -> dict:
    """Ask the user a multiple-choice question and wait for their answer.

    Use this when you hit a genuine fork that only the user can decide and that
    you cannot reasonably infer from the request or the codebase -- for example:
    - Which target/environment to act on (staging vs production).
    - Which of several ambiguous scopes to take (which services/files/modules).
    - Whether to proceed down one of several materially different approaches.

    Do NOT use it for things you can decide yourself, for trivial confirmations
    (bash commands already have their own approval prompt), or to offload a
    decision you were asked to make. Prefer acting; ask only at real forks.

    The question pauses execution, shows the user the options, and returns their
    selection so you can continue in the same turn.

    Args:
        question: The question to ask. Be specific and concise.
        options: 2-10 short option labels for the user to choose from.
        multi_select: If True, the user may pick more than one option.
        allow_other: If True, the user may type a free-text answer instead.
        allow_cancel: If True, the user may cancel without choosing.

    Returns:
        A dict:
        - ``{"ok": True, "selected": ["..."], "cancelled": False}`` on a choice
          (``selected`` is always a list, even for single-select).
        - ``{"ok": True, "selected": [], "cancelled": True}`` if the user
          cancelled -- do not retry the same question; decide how to proceed or
          ask a different question.
        - ``{"ok": False, "error": "..."}`` if the arguments were invalid.
    """
    # Validate arguments -> error dict (never raise into the agent loop).
    if not isinstance(question, str) or not question.strip():
        return {"ok": False, "error": "question must be a non-empty string"}
    if not isinstance(options, list) or not options:
        return {"ok": False, "error": "options must be a non-empty list"}
    labels = [str(o).strip() for o in options if str(o).strip()]
    if not labels:
        return {"ok": False, "error": "options must contain at least one non-empty label"}
    if len(labels) > MAX_OPTIONS:
        return {"ok": False, "error": f"too many options (max {MAX_OPTIONS})"}

    logger.info("ask_user: %s (%d options, multi=%s)", question[:80], len(labels), multi_select)

    asker = _ask_callback
    try:
        if asker is not None:
            result = asker(
                question,
                labels,
                multi_select=multi_select,
                allow_other=allow_other,
                allow_cancel=allow_cancel,
            )
        else:
            from clanker.ui.prompts import select_options

            result = select_options(
                question,
                labels,
                multi_select=multi_select,
                allow_other=allow_other,
                allow_cancel=allow_cancel,
            )
    except Exception as exc:  # noqa: BLE001 - a UI failure must not break the turn
        logger.warning("ask_user selection failed: %s", exc)
        return {"ok": False, "error": f"could not collect an answer: {exc}"}

    selected = list(result.get("selected", []))
    cancelled = bool(result.get("cancelled", False)) or not selected
    logger.info("ask_user: selected=%s cancelled=%s", selected, cancelled)
    return {"ok": True, "selected": selected, "cancelled": cancelled}
