"""Tests for the 413 committed-state unwedge (_compact_oversized_tool_call_args).

Uses a fake async graph so no API keys or network are needed. Skipped if
langchain is not installed.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


def _langchain_available() -> bool:
    try:
        import langchain_core  # noqa: F401

        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _langchain_available(), reason="langchain not installed")


def _ai_write(content, msg_id="m1", call_id="c1"):
    from langchain.messages import AIMessage

    return AIMessage(
        content="",
        id=msg_id,
        tool_calls=[
            {
                "name": "write_file",
                "args": {"file_path": "/x/y.py", "content": content},
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


class _FakeSnapshot:
    def __init__(self, messages):
        self.values = {"messages": messages}


class _FakeGraph:
    def __init__(self, messages):
        self._messages = messages
        self.update = None  # (payload, as_node) captured from aupdate_state

    async def aget_state(self, config):
        return _FakeSnapshot(self._messages)

    async def aupdate_state(self, config, payload, as_node=None):
        self.update = (payload, as_node)


def _settings(max_tokens=4_000):
    return SimpleNamespace(context=SimpleNamespace(max_tool_call_arg_tokens=max_tokens))


def _compact(graph, settings):
    from clanker.ui.streaming import _compact_oversized_tool_call_args

    asyncio.run(_compact_oversized_tool_call_args(graph, {}, settings))


class TestCompactUnwedge:
    def test_shrinks_and_updates_as_tools_node(self) -> None:
        from langchain.messages import HumanMessage

        big = _ai_write("A" * 50_000, msg_id="m1")
        graph = _FakeGraph([HumanMessage(content="hi", id="h1"), big])
        _compact(graph, _settings())

        assert graph.update is not None
        payload, as_node = graph.update
        assert as_node == "tools"
        rewritten = payload["messages"]
        assert len(rewritten) == 1
        # Same id → add_messages upserts in place (no reorder / no pairing change).
        assert rewritten[0].id == "m1"
        assert len(rewritten[0].tool_calls[0]["args"]["content"]) <= 4_000 * 4

    def test_noop_when_nothing_oversized(self) -> None:
        from langchain.messages import HumanMessage

        graph = _FakeGraph([HumanMessage(content="hi", id="h1"), _ai_write("small")])
        _compact(graph, _settings())
        assert graph.update is None

    def test_noop_when_disabled(self) -> None:
        graph = _FakeGraph([_ai_write("A" * 50_000)])
        _compact(graph, _settings(max_tokens=0))
        assert graph.update is None

    def test_never_raises_on_aget_state_error(self) -> None:
        class _BoomGraph:
            async def aget_state(self, config):
                raise RuntimeError("boom")

            async def aupdate_state(self, *a, **k):
                pass

        # Must not propagate — unwedge is best-effort.
        _compact(_BoomGraph(), _settings())

    def test_never_raises_on_empty_state(self) -> None:
        graph = _FakeGraph([])
        _compact(graph, _settings())
        assert graph.update is None
