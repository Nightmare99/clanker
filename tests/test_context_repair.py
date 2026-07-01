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


def _langchain_available() -> bool:
    try:
        import langchain  # noqa: F401
        import langgraph  # noqa: F401

        return True
    except ImportError:
        return False


import pytest  # noqa: E402


@pytest.mark.skipif(not _langchain_available(), reason="langchain/langgraph not installed")
class TestHealOnRealGraph:
    """Integration: _heal_orphaned_tool_calls must repair a real create_agent graph.

    Regression for the reject/interrupt orphan: a tool that raises (command
    rejected) leaves an AIMessage(tool_calls) with no ToolMessage. The heal must
    clear it so the NEXT turn does not 400 with 'tool_use ids without
    tool_result'. This requires aupdate_state(..., as_node="tools"); without it
    the update raises KeyError('model') and the orphan silently persists.
    """

    def _build_agent(self):
        import asyncio

        from langchain.agents import create_agent
        from langchain_core.messages import AIMessage
        from langchain_core.tools import tool
        from langgraph.checkpoint.memory import MemorySaver

        from clanker.tools.bash_tools import CommandRejectedError

        @tool
        def execute_shell(command: str) -> str:
            "run a shell command"
            raise CommandRejectedError("User rejected the command")

        class FakeModel:
            def __init__(self):
                self.n = 0

            def bind_tools(self, *a, **k):
                return self

            async def ainvoke(self, messages, **k):
                self.n += 1
                if self.n == 1:
                    return AIMessage(
                        content="",
                        tool_calls=[{"name": "execute_shell", "args": {"command": "rm x"}, "id": "toolu_x"}],
                    )
                return AIMessage(content="ok")

            profile = {"max_input_tokens": 200000}
            _llm_type = "fake"

        agent = create_agent(model=FakeModel(), tools=[execute_shell], checkpointer=MemorySaver())
        return agent, asyncio

    def test_reject_orphan_is_healed_and_next_turn_ok(self):
        from langchain_core.messages import HumanMessage

        from clanker.context import find_orphaned_tool_call_ids
        from clanker.ui.streaming import _heal_orphaned_tool_calls

        agent, asyncio = self._build_agent()
        cfg = {"configurable": {"thread_id": "t1"}}

        async def run():
            from clanker.tools.bash_tools import CommandRejectedError

            # Turn 1: the tool rejects -> orphan committed.
            try:
                async for _ in agent.astream_events(
                    {"messages": [HumanMessage(content="delete x")]}, config=cfg, version="v2"
                ):
                    pass
            except CommandRejectedError:
                pass

            before = find_orphaned_tool_call_ids((await agent.aget_state(cfg)).values["messages"])
            assert before == ["toolu_x"], "precondition: orphan should exist after reject"

            # Heal (as streaming does before the next turn).
            await _heal_orphaned_tool_calls(agent, cfg)
            after = find_orphaned_tool_call_ids((await agent.aget_state(cfg)).values["messages"])
            assert after == [], "heal must clear the orphan"

            # Turn 2 must not raise the 400 orphan error.
            async for _ in agent.astream_events(
                {"messages": [HumanMessage(content="hello")]}, config=cfg, version="v2"
            ):
                pass
            final = (await agent.aget_state(cfg)).values["messages"]
            assert final[-1].content == "ok"

        asyncio.run(run())
