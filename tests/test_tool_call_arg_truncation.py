"""Tests for ToolCallArgTruncationMiddleware (413 / payload-too-large fix).

Exercises the request-path tool-call argument truncation directly; no API keys or
network needed. Skipped if langchain is not installed (mirrors test_tool_truncation.py).
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


def _ai(tool_calls, **kwargs):
    from langchain.messages import AIMessage

    kwargs.setdefault("content", "")
    return AIMessage(tool_calls=tool_calls, **kwargs)


def _write_call(content, file_path="/x/y.py", call_id="c1"):
    return {
        "name": "write_file",
        "args": {"file_path": file_path, "content": content},
        "id": call_id,
        "type": "tool_call",
    }


# ----------------------------------------------------------------------------
# Pure helper: _truncate_tool_call_args
# ----------------------------------------------------------------------------
class TestTruncateHelper:
    def _trunc(self, message, max_tokens=4_000):
        from clanker.agent.middleware import _truncate_tool_call_args

        return _truncate_tool_call_args(message, max_tokens)

    def test_short_arg_identity(self) -> None:
        msg = _ai([_write_call("small content")])
        assert self._trunc(msg) is msg  # identical object, not a copy

    def test_non_ai_message_passthrough(self) -> None:
        from langchain.messages import HumanMessage

        msg = HumanMessage(content="X" * 50_000)
        assert self._trunc(msg) is msg

    def test_ai_without_tool_calls_passthrough(self) -> None:
        msg = _ai([])
        assert self._trunc(msg) is msg

    def test_long_content_truncated_and_bounded(self) -> None:
        msg = _ai([_write_call("A" * 50_000)])
        out = self._trunc(msg, max_tokens=4_000)  # ~16 KB budget
        assert out is not msg
        content = out.tool_calls[0]["args"]["content"]
        assert len(content) < 50_000
        assert len(content) <= 4_000 * 4
        assert "elided by clanker" in content
        # Non-truncated sibling arg is preserved.
        assert out.tool_calls[0]["args"]["file_path"] == "/x/y.py"

    def test_head_and_tail_preserved(self) -> None:
        content = "HEAD_MARKER" + ("x" * 50_000) + "TAIL_MARKER"
        out = self._trunc(_ai([_write_call(content)]), max_tokens=200)
        new = out.tool_calls[0]["args"]["content"]
        assert new.startswith("HEAD_MARKER")
        assert new.endswith("TAIL_MARKER")
        assert "elided by clanker" in new

    def test_edit_file_both_strings_truncated(self) -> None:
        call = {
            "name": "edit_file",
            "args": {
                "old_string": "O" * 20_000,
                "new_string": "N" * 20_000,
                "preview": True,
            },
            "id": "c1",
            "type": "tool_call",
        }
        out = self._trunc(_ai([call]), max_tokens=1_000)
        args = out.tool_calls[0]["args"]
        assert len(args["old_string"]) <= 1_000 * 4
        assert len(args["new_string"]) <= 1_000 * 4
        # Non-string arg untouched.
        assert args["preview"] is True

    def test_non_string_args_untouched(self) -> None:
        call = {
            "name": "some_tool",
            "args": {"count": 5, "flag": False, "ratio": 1.5},
            "id": "c1",
            "type": "tool_call",
        }
        msg = _ai([call])
        assert self._trunc(msg) is msg  # nothing to truncate → identity

    def test_multiple_tool_calls_independent(self) -> None:
        msg = _ai([_write_call("A" * 50_000, call_id="c1"), _write_call("small", call_id="c2")])
        out = self._trunc(msg, max_tokens=1_000)
        assert len(out.tool_calls[0]["args"]["content"]) <= 4_000
        assert out.tool_calls[1]["args"]["content"] == "small"

    def test_disabled_when_max_zero(self) -> None:
        msg = _ai([_write_call("Z" * 50_000)])
        assert self._trunc(msg, max_tokens=0) is msg

    def test_idempotent(self) -> None:
        msg = _ai([_write_call("A" * 50_000)])
        once = self._trunc(msg, max_tokens=1_000)
        twice = self._trunc(once, max_tokens=1_000)
        assert twice is once  # already truncated → identity on second run

    def test_ids_and_type_preserved(self) -> None:
        msg = _ai([_write_call("A" * 50_000, call_id="abc-123")], id="msg-9")
        out = self._trunc(msg, max_tokens=500)
        assert out.tool_calls[0]["id"] == "abc-123"
        assert out.tool_calls[0]["type"] == "tool_call"
        assert out.tool_calls[0]["name"] == "write_file"
        # Message id preserved — critical for add_messages upsert-by-id.
        assert out.id == "msg-9"


# ----------------------------------------------------------------------------
# Middleware wrappers
# ----------------------------------------------------------------------------
class _StubRequest:
    """Minimal ModelRequest stand-in: .messages + immutable .override()."""

    def __init__(self, messages):
        self.messages = messages
        self.overridden = False

    def override(self, **kwargs):
        new = _StubRequest(kwargs.get("messages", self.messages))
        new.overridden = True
        return new


class TestMiddlewareWrappers:
    def _mw(self, max_tokens=4_000):
        from clanker.agent.middleware import ToolCallArgTruncationMiddleware

        return ToolCallArgTruncationMiddleware(max_tokens=max_tokens)

    def test_wrap_model_call_truncates(self) -> None:
        mw = self._mw()
        big = _ai([_write_call("A" * 50_000)], id="m1")
        seen = {}

        def handler(req):
            seen["req"] = req
            return "RESULT"

        result = mw.wrap_model_call(_StubRequest([big]), handler)
        assert result == "RESULT"
        req = seen["req"]
        assert req.overridden is True
        assert len(req.messages[0].tool_calls[0]["args"]["content"]) <= 4_000 * 4

    def test_wrap_model_call_noop_passes_same_request(self) -> None:
        mw = self._mw()
        small = _ai([_write_call("tiny")])
        original = _StubRequest([small])
        seen = {}

        def handler(req):
            seen["req"] = req
            return "OK"

        mw.wrap_model_call(original, handler)
        # No oversized args → the SAME request object is forwarded (no override).
        assert seen["req"] is original

    def test_async_wrap_model_call_truncates(self) -> None:
        mw = self._mw()
        big = _ai([_write_call("Q" * 50_000)], id="m1")
        seen = {}

        async def handler(req):
            seen["req"] = req
            return "RESULT"

        async def go():
            return await mw.awrap_model_call(_StubRequest([big]), handler)

        result = asyncio.run(go())
        assert result == "RESULT"
        assert seen["req"].overridden is True
        assert len(seen["req"].messages[0].tool_calls[0]["args"]["content"]) <= 4_000 * 4

    def test_real_model_request_override_api(self) -> None:
        # Guard against a langchain bump changing ModelRequest.override(messages=...).
        from langchain.agents.middleware.types import ModelRequest

        assert hasattr(ModelRequest, "override")
