"""Utilities for turning Copilot SDK failures into useful diagnostics."""

from __future__ import annotations

import asyncio
from typing import Any

GENERIC_ERROR_MESSAGES = {
    "",
    "unknown error",
    "none",
    "throw() was called",
}

WRAPPER_ERROR_MESSAGES = {
    "generator didn't stop after throw()",
}

SENSITIVE_KEY_FRAGMENTS = (
    "token",
    "secret",
    "password",
    "authorization",
    "api_key",
    "apikey",
    "auth",
)


def _truncate(value: str, max_length: int = 300) -> str:
    """Trim long values so logs stay readable."""
    if len(value) <= max_length:
        return value
    return value[: max_length - 3] + "..."


def _is_sensitive_key(key: str) -> bool:
    """Check whether a field name likely contains secrets."""
    lowered = key.lower()
    return any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS)


def _coerce_text(value: Any) -> str:
    """Convert a value to compact display text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _message_from_exception(exc: BaseException) -> str:
    """Extract the most useful message from a single exception object."""
    candidates: list[str] = []

    direct = _coerce_text(exc)
    if direct:
        candidates.append(direct)

    args = getattr(exc, "args", ())
    for arg in args:
        text = _coerce_text(arg)
        if text:
            candidates.append(text)

    for attr in ("message", "detail", "error", "description", "reason"):
        if hasattr(exc, attr):
            text = _coerce_text(getattr(exc, attr))
            if text:
                candidates.append(text)

    for candidate in candidates:
        if candidate.lower() not in GENERIC_ERROR_MESSAGES:
            return _truncate(candidate)

    return _truncate(candidates[0]) if candidates else ""


def _iter_exception_chain(exc: BaseException) -> list[BaseException]:
    """Follow cause/context links without looping forever."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc

    while current is not None and id(current) not in seen:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__

    return chain


def _extract_event_message(recent_events: list[dict[str, Any]] | None) -> str:
    """Look for a concrete session error/warning message in recent SDK events."""
    if not recent_events:
        return ""

    for event in reversed(recent_events):
        for key in ("message", "detail", "error", "reason"):
            value = _coerce_text(event.get(key))
            if value:
                return _truncate(value)
    return ""


def summarize_sdk_event(event_type: str, data: Any) -> dict[str, Any]:
    """Create a sanitized, compact summary of an SDK event."""
    summary: dict[str, Any] = {"type": event_type}

    if data is None:
        return summary

    if hasattr(data, "model_dump"):
        try:
            data = data.model_dump()
        except Exception:
            pass
    elif hasattr(data, "__dict__") and not isinstance(data, dict):
        try:
            data = vars(data)
        except Exception:
            pass

    if isinstance(data, dict):
        for key, value in list(data.items())[:12]:
            if _is_sensitive_key(str(key)):
                summary[key] = "<redacted>"
                continue

            if key in {"content", "delta_content", "deltaContent", "result"}:
                text = _coerce_text(value)
                if text:
                    summary[f"{key}_preview"] = _truncate(text, 120)
                    summary[f"{key}_length"] = len(text)
                continue

            if key in {"arguments", "toolArgs", "tool_args"} and isinstance(value, dict):
                summary["argument_keys"] = sorted(value.keys())
                continue

            if isinstance(value, (str, int, float, bool)) or value is None:
                summary[key] = _truncate(str(value), 120) if isinstance(value, str) else value
            elif isinstance(value, dict):
                nested: dict[str, Any] = {}
                for nested_key, nested_value in list(value.items())[:8]:
                    if _is_sensitive_key(str(nested_key)):
                        nested[nested_key] = "<redacted>"
                    elif isinstance(nested_value, (str, int, float, bool)) or nested_value is None:
                        nested[nested_key] = (
                            _truncate(str(nested_value), 120)
                            if isinstance(nested_value, str)
                            else nested_value
                        )
                    else:
                        nested[nested_key] = type(nested_value).__name__
                summary[key] = nested
            else:
                summary[key] = type(value).__name__

        return summary

    if isinstance(data, str):
        summary["message"] = _truncate(data, 200)
    else:
        summary["data_type"] = type(data).__name__
        text = _coerce_text(data)
        if text:
            summary["message"] = _truncate(text, 200)

    return summary


def summarize_copilot_exception(
    exc: BaseException,
    recent_events: list[dict[str, Any]] | None = None,
    operation: str = "Copilot request",
) -> str:
    """Turn noisy SDK exceptions into a cleaner user-facing message."""
    chain = _iter_exception_chain(exc)
    event_message = _extract_event_message(recent_events)
    chain_messages = [msg for item in chain if (msg := _message_from_exception(item))]
    best_message = next((msg for msg in chain_messages if msg.lower() not in GENERIC_ERROR_MESSAGES), "")
    if best_message.lower() in WRAPPER_ERROR_MESSAGES:
        best_message = next(
            (
                msg
                for msg in chain_messages
                if msg.lower() not in GENERIC_ERROR_MESSAGES
                and msg.lower() not in WRAPPER_ERROR_MESSAGES
            ),
            best_message,
        )
    generic_message = chain_messages[0] if chain_messages else ""

    if isinstance(exc, asyncio.TimeoutError):
        return f"{operation} timed out."

    if any(isinstance(item, asyncio.TimeoutError) for item in chain):
        return f"{operation} timed out."

    if isinstance(exc, ImportError):
        return _message_from_exception(exc) or f"{operation} failed."

    combined_messages = " | ".join(m.lower() for m in chain_messages if m)
    if "throw() was called" in combined_messages:
        if event_message:
            return f"{operation} aborted unexpectedly. Last SDK error: {event_message}"
        if best_message and best_message.lower() != "throw() was called":
            return f"{operation} failed: {best_message}"
        return f"{operation} aborted unexpectedly inside the Copilot SDK."

    if event_message:
        return f"{operation} failed: {event_message}"

    if best_message:
        return f"{operation} failed: {best_message}"

    if generic_message:
        return f"{operation} failed: {generic_message}"

    return f"{operation} failed unexpectedly."


def exception_chain_details(exc: BaseException) -> list[dict[str, Any]]:
    """Serialize the exception chain for structured logging."""
    details: list[dict[str, Any]] = []
    for item in _iter_exception_chain(exc):
        detail: dict[str, Any] = {
            "type": type(item).__name__,
            "message": _message_from_exception(item),
        }
        if getattr(item, "args", None):
            detail["args"] = [_truncate(_coerce_text(arg), 200) for arg in item.args]
        details.append(detail)
    return details


def log_copilot_error(
    logger,
    exc: BaseException,
    *,
    operation: str,
    recent_events: list[dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Emit a detailed log entry for Copilot failures."""
    logger.exception(
        "Copilot failure during %s | summary=%s | context=%s | exception_chain=%s | recent_events=%s",
        operation,
        summarize_copilot_exception(exc, recent_events=recent_events, operation=operation),
        context or {},
        exception_chain_details(exc),
        recent_events or [],
    )
