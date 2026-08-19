"""RobustSummarizationMiddleware's internal compaction model call shows up in
graph.astream_events() as its own on_chat_model_start/stream/end events --
provider-agnostic, not specific to any one backend. Before this fix,
streaming.py treated those events exactly like the real agent turn's output:
the compaction call's own generated summary text (and any "thinking"-style
content within it, unthemed) got accumulated into current_response/
current_thinking and dumped into the transcript as if the agent had said it.

The fix: RobustSummarizationMiddleware tags its internal call(s) with
config={"metadata": {"lc_source": "summarization"}} (see summarization.py).
streaming.py now checks that metadata (not a call-count/position heuristic)
to suppress accumulating that call's content, and shows a single "Compacting
conversation history..." message in both console and TUI chat log instead.

These tests drive the REAL astream_events pipeline (a real compiled LangGraph
agent with the real RobustSummarizationMiddleware and a streaming-capable
fake chat model) through stream_agent_response_async, so they reproduce the
actual bug end-to-end rather than asserting against a description of it.
GenericFakeChatModel is used (not FakeMessagesListChatModel) because it
implements `_stream`, so -- exactly like real providers -- invoking it inside
astream_events() emits real on_chat_model_stream chunk events, which is the
code path this bug (and its fix) actually lives in.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from clanker.agent.summarization import RobustSummarizationMiddleware

SUMMARY_TEXT = (
    "## SESSION INTENT\nThe user asked about X.\n\n"
    "## SUMMARY\nWe discussed Y and decided Z.\n\n"
    "## ARTIFACTS\nNone\n\n## NEXT STEPS\nNone"
)


def _build_compacting_agent(final_answer: str = "The real answer."):
    """A real compiled agent whose summarization middleware WILL trigger on
    the second turn (trigger=("messages", 2)).

    Three model calls happen across the two turns this test drives: turn 1's
    own answer, then (on turn 2, once the trigger fires) the compaction's
    internal summary call, then turn 2's own answer -- in that chronological
    order, since before_model runs before the turn's model node.
    """
    model = GenericFakeChatModel(
        messages=iter([
            AIMessage(content="turn 1 answer (unused by assertions)"),
            AIMessage(content=SUMMARY_TEXT),
            AIMessage(content=final_answer),
        ])
    )
    model.profile = {"max_input_tokens": 100_000}

    summarization = RobustSummarizationMiddleware(
        model=model, trigger=("messages", 2), keep=("messages", 1)
    )
    checkpointer = MemorySaver()
    agent = create_agent(
        model=model, tools=[], middleware=[summarization],
        checkpointer=checkpointer, system_prompt="test",
    )
    return agent, model


async def _run_turn(agent, console, config, message: str):
    from clanker.ui.streaming import stream_agent_response_async

    with patch(
        "clanker.agent.create_agent_graph_async",
        new_callable=AsyncMock,
        return_value=(agent, None),
    ), patch("clanker.ui.streaming._teardown_live_displays"), patch(
        "clanker.ui.streaming._heal_orphaned_tool_calls", new_callable=AsyncMock
    ):
        from clanker.config.settings import Settings

        return await stream_agent_response_async(
            settings=Settings(),
            checkpointer=None,
            state={"messages": [HumanMessage(content=message)]},
            config=config,
            console=console,
        )


class TestCompactionNotDumpedInTranscript:
    async def test_summary_text_never_reaches_chat_log_as_assistant_message(self) -> None:
        agent, _ = _build_compacting_agent()
        config = {"configurable": {"thread_id": "t1"}}
        console = MagicMock()
        chat_log = MagicMock()
        textual_app = MagicMock()
        textual_app.get_chat_log.return_value = chat_log
        console._textual_app = textual_app

        # Seed turn 1 directly against the graph (not through streaming) so
        # turn 2's total message count crosses the trigger threshold.
        await agent.ainvoke({"messages": [HumanMessage(content="m1")]}, config)

        result = await _run_turn(agent, console, config, "m2")

        # The compaction's own generated text must never appear as if the
        # agent said it, in either the console or the TUI chat log.
        for call in console.print_assistant_message.call_args_list:
            assert "SESSION INTENT" not in call.args[0]
        for call in chat_log.add_message.call_args_list:
            text = call.args[0]
            assert "SESSION INTENT" not in text
            assert "SUMMARY" not in text or "Compacting" in text

        # The real turn's own answer must still come through normally.
        assert result.response == "The real answer."

    async def test_compacting_message_shown_once_in_console_and_chat_log(self) -> None:
        agent, _ = _build_compacting_agent()
        config = {"configurable": {"thread_id": "t2"}}
        console = MagicMock()
        chat_log = MagicMock()
        textual_app = MagicMock()
        textual_app.get_chat_log.return_value = chat_log
        console._textual_app = textual_app

        await agent.ainvoke({"messages": [HumanMessage(content="m1")]}, config)
        await _run_turn(agent, console, config, "m2")

        info_calls = [
            c for c in console.print_info.call_args_list
            if "Compacting conversation history" in c.args[0]
        ]
        chat_log_calls = [
            c for c in chat_log.add_message.call_args_list
            if "Compacting conversation history" in c.args[0]
        ]
        assert len(info_calls) == 1
        assert len(chat_log_calls) == 1

    async def test_normal_turn_without_compaction_is_unaffected(self) -> None:
        """A turn that never triggers compaction (trigger threshold far above
        message count) must show the real response normally, with no
        "Compacting" message at all."""
        model = GenericFakeChatModel(messages=iter([AIMessage(content="Hello there!")]))
        model.profile = {"max_input_tokens": 100_000}
        summarization = RobustSummarizationMiddleware(
            model=model, trigger=("messages", 1000), keep=("messages", 500)
        )
        checkpointer = MemorySaver()
        agent = create_agent(
            model=model, tools=[], middleware=[summarization],
            checkpointer=checkpointer, system_prompt="test",
        )
        config = {"configurable": {"thread_id": "t3"}}
        console = MagicMock()
        chat_log = MagicMock()
        textual_app = MagicMock()
        textual_app.get_chat_log.return_value = chat_log
        console._textual_app = textual_app

        result = await _run_turn(agent, console, config, "hi")

        assert result.response == "Hello there!"
        assert not any(
            "Compacting" in c.args[0] for c in console.print_info.call_args_list
        )
        assert not any(
            "Compacting" in c.args[0] for c in chat_log.add_message.call_args_list
        )
