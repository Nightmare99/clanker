"""Tests for ToolResultTruncationMiddleware (BYOK mode).

Exercises the tool-result truncation pipeline directly; no API keys or network
needed. Skipped if langchain is not installed (mirrors tests/test_agent.py).
"""

from __future__ import annotations

import asyncio

import pytest


def _langchain_available() -> bool:
    try:
        import langchain_core  # noqa: F401

        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _langchain_available(), reason="langchain not installed")


def _mw(max_tokens: int = 100):
    from clanker.agent.middleware import ToolResultTruncationMiddleware

    return ToolResultTruncationMiddleware(max_tokens=max_tokens)


def _tool_message(content, **kwargs):
    from langchain.messages import ToolMessage

    kwargs.setdefault("tool_call_id", "tc-1")
    kwargs.setdefault("name", "read_file")
    return ToolMessage(content=content, **kwargs)


def _run(mw, result):
    """Invoke the sync wrapper with a handler that returns ``result``."""
    return mw.wrap_tool_call("req", lambda _req: result)


class TestPassthrough:
    def test_short_string_unchanged(self) -> None:
        msg = _tool_message("small output")
        out = _run(_mw(max_tokens=100), msg)
        assert out is msg  # identical object, not a copy

    def test_non_tool_message_passthrough(self) -> None:
        # A wrap_tool_call handler may return a Command or other object.
        sentinel = {"not": "a tool message"}
        out = _run(_mw(max_tokens=1), sentinel)
        assert out is sentinel

    def test_disabled_when_max_zero(self) -> None:
        big = "Z" * 100_000
        msg = _tool_message(big)
        out = _run(_mw(max_tokens=0), msg)
        assert out is msg
        assert out.content == big


class TestStringTruncation:
    def test_long_string_truncated_and_bounded(self) -> None:
        max_tokens = 100  # ~400 char budget
        msg = _tool_message("A" * 50_000)
        out = _run(_mw(max_tokens=max_tokens), msg)
        assert out is not msg
        assert len(out.content) < 50_000
        assert len(out.content) <= max_tokens * 4
        assert "truncated by clanker" in out.content

    def test_head_and_tail_preserved(self) -> None:
        content = "HEAD_MARKER" + ("x" * 50_000) + "TAIL_MARKER"
        out = _run(_mw(max_tokens=200), _tool_message(content))
        assert out.content.startswith("HEAD_MARKER")
        assert out.content.endswith("TAIL_MARKER")
        assert "truncated by clanker" in out.content

    def test_tool_message_fields_preserved(self) -> None:
        msg = _tool_message("B" * 50_000, tool_call_id="abc-123", name="grep_search")
        out = _run(_mw(max_tokens=50), msg)
        assert out.tool_call_id == "abc-123"
        assert out.name == "grep_search"

    def test_tiny_budget_still_bounded(self) -> None:
        # Budget smaller than the truncation marker itself must not overflow.
        msg = _tool_message("Y" * 50_000)
        out = _run(_mw(max_tokens=10), msg)  # 40-char budget < marker length
        assert len(out.content) <= 40


class TestMultimodalContent:
    def test_text_truncated_image_preserved(self) -> None:
        content = [
            {"type": "text", "text": "T" * 50_000},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAABBBBCCCC"}},
        ]
        out = _run(_mw(max_tokens=100), _tool_message(content))
        assert isinstance(out.content, list)
        text_block = next(b for b in out.content if b.get("type") == "text")
        image_block = next(b for b in out.content if b.get("type") == "image_url")
        # Text was cut...
        assert len(text_block["text"]) < 50_000
        assert "truncated by clanker" in text_block["text"]
        # ...image survived byte-for-byte.
        assert image_block["image_url"]["url"] == "data:image/png;base64,AAAABBBBCCCC"

    def test_small_multimodal_unchanged(self) -> None:
        content = [
            {"type": "text", "text": "tiny"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]
        msg = _tool_message(content)
        out = _run(_mw(max_tokens=100), msg)
        assert out is msg


class TestAsync:
    def test_async_truncates(self) -> None:
        from clanker.agent.middleware import ToolResultTruncationMiddleware

        mw = ToolResultTruncationMiddleware(max_tokens=100)
        msg = _tool_message("Q" * 50_000)

        async def handler(_req):
            return msg

        async def go():
            return await mw.awrap_tool_call("req", handler)

        out = asyncio.run(go())
        assert out is not msg
        assert len(out.content) <= 100 * 4
        assert "truncated by clanker" in out.content

    def test_async_short_passthrough(self) -> None:
        from clanker.agent.middleware import ToolResultTruncationMiddleware

        mw = ToolResultTruncationMiddleware(max_tokens=100)
        msg = _tool_message("ok")

        async def handler(_req):
            return msg

        out = asyncio.run(mw.awrap_tool_call("req", handler))
        assert out is msg
