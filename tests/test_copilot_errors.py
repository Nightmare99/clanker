"""Tests for Copilot error summarization utilities."""

import ast
from pathlib import Path

from clanker.copilot.errors import (
    exception_chain_details,
    summarize_copilot_exception,
    summarize_sdk_event,
)


def test_summarize_copilot_exception_prefers_event_message_for_generic_sdk_error() -> None:
    exc = RuntimeError("throw() was called")
    recent_events = [{"type": "session.error", "message": "Tool execution failed in bash"}]

    message = summarize_copilot_exception(
        exc,
        recent_events=recent_events,
        operation="Copilot response",
    )

    assert message == "Copilot response aborted unexpectedly. Last SDK error: Tool execution failed in bash"


def test_summarize_copilot_exception_uses_exception_chain_message() -> None:
    try:
        try:
            raise ValueError("Remote MCP server disconnected")
        except ValueError as inner:
            raise RuntimeError("throw() was called") from inner
    except RuntimeError as exc:
        message = summarize_copilot_exception(exc, operation="Copilot session creation")

    assert message == "Copilot session creation failed: Remote MCP server disconnected"


def test_exception_chain_details_includes_inner_exception_message() -> None:
    try:
        try:
            raise ValueError("Better detail")
        except ValueError as inner:
            raise RuntimeError("throw() was called") from inner
    except RuntimeError as exc:
        details = exception_chain_details(exc)

    assert details[0]["type"] == "RuntimeError"
    assert details[1]["type"] == "ValueError"
    assert details[1]["message"] == "Better detail"


def test_summarize_sdk_event_redacts_sensitive_fields() -> None:
    summary = summarize_sdk_event(
        "session.error",
        {
            "message": "bad things happened",
            "token": "secret-token",
            "arguments": {"command": "pytest", "api_key": "abc"},
        },
    )

    assert summary["message"] == "bad things happened"
    assert summary["token"] == "<redacted>"
    assert summary["argument_keys"] == ["api_key", "command"]


def test_summarize_copilot_exception_ignores_wrapper_runtime_error() -> None:
    try:
        try:
            raise TimeoutError("Timeout after 60.0s waiting for session.idle")
        except TimeoutError as inner:
            raise RuntimeError("generator didn't stop after throw()") from inner
    except RuntimeError as exc:
        message = summarize_copilot_exception(exc, operation="Copilot response")

    assert message == "Copilot response timed out."


def test_streaming_copilot_async_does_not_reimport_get_logger() -> None:
    source = Path("src/clanker/ui/streaming.py").read_text(encoding="utf-8")
    module = ast.parse(source)

    outer = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "stream_copilot_response_sync"
    )
    inner = next(
        node for node in outer.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_stream_copilot_async"
    )

    shadowing_imports = [
        node for node in ast.walk(inner)
        if isinstance(node, ast.ImportFrom)
        and node.module == "clanker.logging"
        and any(alias.name == "get_logger" for alias in node.names)
    ]

    assert shadowing_imports == []


def test_suppress_subprocess_stderr_has_no_yield_in_except_handler() -> None:
    source = Path("src/clanker/ui/streaming.py").read_text(encoding="utf-8")
    module = ast.parse(source)

    suppress_fn = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "_suppress_subprocess_stderr"
    )
    except_handlers = [node for node in ast.walk(suppress_fn) if isinstance(node, ast.ExceptHandler)]

    yields_inside_except = [
        node
        for handler in except_handlers
        for node in ast.walk(handler)
        if isinstance(node, (ast.Yield, ast.YieldFrom))
    ]

    assert yields_inside_except == []


def test_streaming_copilot_async_uses_send_not_send_and_wait() -> None:
    source = Path("src/clanker/ui/streaming.py").read_text(encoding="utf-8")
    module = ast.parse(source)

    outer = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "stream_copilot_response_sync"
    )
    inner = next(
        node for node in outer.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_stream_copilot_async"
    )

    call_names = [
        node.func.attr
        for node in ast.walk(inner)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]

    assert "send" in call_names
    assert "send_and_wait" not in call_names


def test_streaming_copilot_async_does_not_clear_private_event_handlers() -> None:
    source = Path("src/clanker/ui/streaming.py").read_text(encoding="utf-8")

    assert "._event_handlers.clear()" not in source
    assert '"assistant.streaming_delta"' in source
