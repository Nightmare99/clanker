"""Tests for conversation-history repair (orphaned tool_use after interrupt)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from clanker.context import find_orphaned_tool_call_ids, make_tool_result_stubs
from clanker.context.repair import INTERRUPTED_TOOL_RESULT


def _ai_with_tools(*ids):
    return AIMessage(
        content="working",
        tool_calls=[{"name": "execute_shell", "args": {}, "id": i} for i in ids],
    )


class TestFindOrphans:
    def test_no_tool_calls_no_orphans(self):
        msgs = [HumanMessage(content="hi"), AIMessage(content="hello")]
        assert find_orphaned_tool_call_ids(msgs) == []

    def test_satisfied_tool_call_not_orphan(self):
        msgs = [
            HumanMessage(content="q"),
            _ai_with_tools("a"),
            ToolMessage(content="result", tool_call_id="a"),
        ]
        assert find_orphaned_tool_call_ids(msgs) == []

    def test_single_orphan_detected(self):
        msgs = [HumanMessage(content="q"), _ai_with_tools("a")]
        assert find_orphaned_tool_call_ids(msgs) == ["a"]

    def test_multiple_orphans_in_order(self):
        # The exact shape from the reported bug: two unsatisfied tool_use ids.
        msgs = [HumanMessage(content="q"), _ai_with_tools("toolu_014", "toolu_01G")]
        assert find_orphaned_tool_call_ids(msgs) == ["toolu_014", "toolu_01G"]

    def test_partial_satisfaction(self):
        # One of two tool calls got a result; the other is orphaned.
        msgs = [
            HumanMessage(content="q"),
            _ai_with_tools("a", "b"),
            ToolMessage(content="r", tool_call_id="a"),
        ]
        assert find_orphaned_tool_call_ids(msgs) == ["b"]

    def test_deduplicates(self):
        msgs = [_ai_with_tools("a"), _ai_with_tools("a")]
        assert find_orphaned_tool_call_ids(msgs) == ["a"]

    def test_valid_history_with_many_pairs(self):
        msgs = [
            HumanMessage(content="q1"),
            _ai_with_tools("a"),
            ToolMessage(content="r", tool_call_id="a"),
            AIMessage(content="done"),
            HumanMessage(content="q2"),
            _ai_with_tools("b", "c"),
            ToolMessage(content="r", tool_call_id="b"),
            ToolMessage(content="r", tool_call_id="c"),
        ]
        assert find_orphaned_tool_call_ids(msgs) == []


class TestMakeStubs:
    def test_one_stub_per_id_in_order(self):
        stubs = make_tool_result_stubs(["x", "y"])
        assert [s.tool_call_id for s in stubs] == ["x", "y"]
        assert all(isinstance(s, ToolMessage) for s in stubs)
        assert all(s.content == INTERRUPTED_TOOL_RESULT for s in stubs)

    def test_empty(self):
        assert make_tool_result_stubs([]) == []

    def test_stubs_heal_the_orphans(self):
        # Appending the stubs must make find_orphaned return empty.
        msgs = [HumanMessage(content="q"), _ai_with_tools("a", "b")]
        orphans = find_orphaned_tool_call_ids(msgs)
        healed = msgs + make_tool_result_stubs(orphans)
        assert find_orphaned_tool_call_ids(healed) == []
