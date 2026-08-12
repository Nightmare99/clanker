"""Tests for the unified compaction path shared by auto-compaction (middleware)
and the manual `/compact` command.

Covers: RobustSummarizationMiddleware.compact()/acompact() (the single shared
implementation both paths call), the `compaction_count` state marker that lets
the streaming loop detect auto-compaction precisely, and
sync_conversation_after_auto_compaction() (the app-layer sync both entry
points use to keep `conversation_messages` from drifting out of sync with
what the model actually retains).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage


def _langchain_available() -> bool:
    try:
        import langchain_core  # noqa: F401

        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _langchain_available(), reason="langchain not installed")


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeModel:
    def __init__(self, text: str = "## SESSION INTENT\nx\n\n## SUMMARY\ny\n\n## ARTIFACTS\nNone\n\n## NEXT STEPS\nNone") -> None:
        self.text = text
        self._llm_type = "fake-chat"
        self.profile = {"max_input_tokens": 100_000}

    def invoke(self, *args, **kwargs):
        return FakeResponse(self.text)

    def with_retry(self, *args, **kwargs):
        # SummarizationMiddleware.__init__ calls model.with_retry() to build
        # its internal retrying summary model. Our overridden summary
        # pipeline never uses that attribute (it calls self.model directly),
        # so just returning self satisfies construction.
        return self

    async def ainvoke(self, *args, **kwargs):
        return FakeResponse(self.text)


def _messages(*pairs):
    out = []
    for kind, content in pairs:
        if kind == "h":
            out.append(HumanMessage(content=content))
        elif kind == "a":
            out.append(AIMessage(content=content))
        else:  # pragma: no cover
            raise ValueError(kind)
    return out


def _build_middleware(model, **kwargs):
    from clanker.agent.summarization import RobustSummarizationMiddleware

    kwargs.setdefault("trigger", ("messages", 100))  # high threshold -- won't fire unless forced
    kwargs.setdefault("keep", ("messages", 10))
    return RobustSummarizationMiddleware(model=model, **kwargs)


class TestCompactShared:
    """RobustSummarizationMiddleware.compact() -- the single implementation
    behind both the automatic trigger and the manual `/compact` command."""

    def test_not_due_returns_none_without_force(self) -> None:
        mw = _build_middleware(FakeModel())
        messages = _messages(("h", "hi"), ("a", "hello"))
        assert mw.compact(messages, force=False) is None

    def test_force_compacts_even_when_not_due(self) -> None:
        mw = _build_middleware(FakeModel())
        messages = _messages(("h", "msg1"), ("a", "msg2"), ("h", "msg3"), ("a", "msg4"))
        result = mw.compact(messages, force=True)
        assert result is not None
        assert result.summarized_count >= 1
        assert "Here is a summary of the conversation to date" in result.new_messages[0].content

    def test_force_with_cutoff_zero_falls_back_to_len_minus_one(self) -> None:
        # keep=10 messages, but only 2 given -> natural cutoff is 0.
        mw = _build_middleware(FakeModel())
        messages = _messages(("h", "only"), ("a", "two"))
        result = mw.compact(messages, force=True)
        assert result is not None
        # First message summarized, last preserved verbatim.
        assert result.summarized_count == 1
        assert len(result.preserved_messages) == 1
        assert result.preserved_messages[0].content == "two"

    def test_graph_state_update_shape(self) -> None:
        from langchain_core.messages import RemoveMessage
        from langgraph.graph.message import REMOVE_ALL_MESSAGES

        mw = _build_middleware(FakeModel())
        messages = _messages(("h", "a"), ("a", "b"), ("h", "c"), ("a", "d"))
        result = mw.compact(messages, force=True)
        update = result.graph_state_update
        assert isinstance(update["messages"][0], RemoveMessage)
        assert update["messages"][0].id == REMOVE_ALL_MESSAGES
        assert update["messages"][1:] == result.compacted_messages

    @pytest.mark.asyncio
    async def test_acompact_mirrors_compact(self) -> None:
        mw = _build_middleware(FakeModel())
        messages = _messages(("h", "msg1"), ("a", "msg2"), ("h", "msg3"), ("a", "msg4"))
        result = await mw.acompact(messages, force=True)
        assert result is not None
        assert "Here is a summary of the conversation to date" in result.new_messages[0].content


class TestRunCompaction:
    """run_compaction() -- builds a middleware from settings, used by both
    the `/compact` command and the auto-compaction sync."""

    def test_builds_middleware_from_settings_and_compacts(self) -> None:
        from clanker.agent.summarization import run_compaction
        from clanker.config.settings import Settings

        settings = Settings()
        settings.context.keep_recent_turns = 1
        messages = _messages(("h", "msg1"), ("a", "msg2"), ("h", "msg3"), ("a", "msg4"))

        result = run_compaction(messages, FakeModel(), settings, force=True)
        assert result is not None
        assert result.summarized_count == 2

    def test_not_forced_respects_trigger(self) -> None:
        from clanker.agent.summarization import run_compaction
        from clanker.config.settings import Settings

        settings = Settings()  # default 80% trigger, tiny conversation won't hit it
        messages = _messages(("h", "hi"), ("a", "hello"))

        result = run_compaction(messages, FakeModel(), settings, force=False)
        assert result is None


class TestBeforeModelStateMarker:
    """before_model/abefore_model stamp `compaction_count` so external code
    (the streaming loop) can detect compaction precisely."""

    def test_before_model_increments_counter_on_compaction(self) -> None:
        mw = _build_middleware(FakeModel(), trigger=("messages", 2), keep=("messages", 1))
        messages = _messages(("h", "a"), ("a", "b"), ("h", "c"))
        state = {"messages": messages, "compaction_count": 3}
        update = mw.before_model(state, runtime=MagicMock())
        assert update is not None
        assert update["compaction_count"] == 4

    def test_before_model_returns_none_and_no_counter_when_not_due(self) -> None:
        mw = _build_middleware(FakeModel(), trigger=("messages", 100))
        messages = _messages(("h", "a"), ("a", "b"))
        state = {"messages": messages, "compaction_count": 0}
        assert mw.before_model(state, runtime=MagicMock()) is None

    @pytest.mark.asyncio
    async def test_abefore_model_increments_counter_on_compaction(self) -> None:
        mw = _build_middleware(FakeModel(), trigger=("messages", 2), keep=("messages", 1))
        messages = _messages(("h", "a"), ("a", "b"), ("h", "c"))
        state = {"messages": messages}
        update = await mw.abefore_model(state, runtime=MagicMock())
        assert update is not None
        assert update["compaction_count"] == 1  # absent in state -> defaults to 0


class TestCompactionCountEndToEnd:
    """The `compaction_count` state field survives a real LangGraph run."""

    def test_counter_increments_across_turns_via_real_graph(self) -> None:
        from langchain.agents import create_agent
        from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
        from langgraph.checkpoint.memory import MemorySaver

        from clanker.agent.summarization import RobustSummarizationMiddleware

        model = FakeMessagesListChatModel(responses=[AIMessage(content="summary text")] * 10)
        model.profile = {"max_input_tokens": 100_000}

        summarization = RobustSummarizationMiddleware(
            model=model, trigger=("messages", 2), keep=("messages", 1)
        )
        checkpointer = MemorySaver()
        agent = create_agent(
            model=model, tools=[], middleware=[summarization],
            checkpointer=checkpointer, system_prompt="test",
        )

        config = {"configurable": {"thread_id": "t1"}}
        agent.invoke({"messages": [HumanMessage(content="m1")]}, config)
        assert agent.get_state(config).values.get("compaction_count", 0) == 0

        agent.invoke({"messages": [HumanMessage(content="m2")]}, config)
        assert agent.get_state(config).values.get("compaction_count", 0) == 1


class TestCompactionOccurredDetection:
    """stream_agent_response_async detects compaction via a precise
    checkpoint-state diff (compaction_count before vs after), not a
    call-count heuristic."""

    @staticmethod
    def _make_graph(compaction_counts: list[int]):
        """A mock graph whose aget_state() returns successive counter values."""
        calls = {"n": 0}

        async def fake_aget_state(config):
            idx = min(calls["n"], len(compaction_counts) - 1)
            calls["n"] += 1
            return SimpleNamespace(values={"compaction_count": compaction_counts[idx]})

        mock_graph = MagicMock()
        mock_graph.aget_state = fake_aget_state

        async def astream_events(state, config, version):
            return
            yield  # pragma: no cover - empty async generator

        mock_graph.astream_events = astream_events
        return mock_graph

    @pytest.mark.asyncio
    async def test_reports_true_when_counter_advances(self) -> None:
        from clanker.ui.streaming import stream_agent_response_async

        mock_graph = self._make_graph([0, 1])  # before=0, after=1

        with patch(
            "clanker.agent.create_agent_graph_async",
            new_callable=AsyncMock,
            return_value=(mock_graph, MagicMock()),
        ), patch("clanker.ui.streaming._teardown_live_displays"), patch(
            "clanker.ui.streaming._heal_orphaned_tool_calls", new_callable=AsyncMock
        ):
            result = await stream_agent_response_async(
                settings=MagicMock(),
                checkpointer=None,
                state={"messages": []},
                config={"configurable": {"thread_id": "test"}},
                console=MagicMock(),
            )

        assert result.summarization_occurred is True

    @pytest.mark.asyncio
    async def test_reports_false_when_counter_unchanged(self) -> None:
        from clanker.ui.streaming import stream_agent_response_async

        mock_graph = self._make_graph([0, 0])  # before=0, after=0

        with patch(
            "clanker.agent.create_agent_graph_async",
            new_callable=AsyncMock,
            return_value=(mock_graph, MagicMock()),
        ), patch("clanker.ui.streaming._teardown_live_displays"), patch(
            "clanker.ui.streaming._heal_orphaned_tool_calls", new_callable=AsyncMock
        ):
            result = await stream_agent_response_async(
                settings=MagicMock(),
                checkpointer=None,
                state={"messages": []},
                config={"configurable": {"thread_id": "test"}},
                console=MagicMock(),
            )

        assert result.summarization_occurred is False


class TestSyncConversationAfterAutoCompaction:
    """The app-layer sync both the TUI and the legacy REPL call after
    auto-compaction, mirroring exactly what `/compact` does."""

    def test_replaces_conversation_messages_and_saves_snapshot(self) -> None:
        from clanker.cli import sync_conversation_after_auto_compaction
        from clanker.config.settings import Settings

        settings = Settings()
        settings.context.keep_recent_turns = 1
        conversation_messages = _messages(
            ("h", "msg1"), ("a", "msg2"), ("h", "msg3"), ("a", "msg4")
        )
        session_manager = MagicMock()
        console = MagicMock()

        with patch("clanker.cli.create_model", return_value=FakeModel()):
            sync_conversation_after_auto_compaction(
                conversation_messages, session_manager, settings, console
            )

        assert "Here is a summary of the conversation to date" in conversation_messages[0].content
        session_manager.save_conversation_snapshot.assert_called_once_with(conversation_messages)
        console.print_info.assert_called_once()

    def test_also_mirrors_to_chat_log_when_provided(self) -> None:
        from clanker.cli import sync_conversation_after_auto_compaction
        from clanker.config.settings import Settings

        settings = Settings()
        settings.context.keep_recent_turns = 1
        conversation_messages = _messages(
            ("h", "msg1"), ("a", "msg2"), ("h", "msg3"), ("a", "msg4")
        )
        session_manager = MagicMock()
        console = MagicMock()
        chat_log = MagicMock()

        with patch("clanker.cli.create_model", return_value=FakeModel()):
            sync_conversation_after_auto_compaction(
                conversation_messages, session_manager, settings, console, chat_log
            )

        chat_log.add_message.assert_called_once()

    def test_noop_when_nothing_to_compact(self) -> None:
        from clanker.cli import sync_conversation_after_auto_compaction
        from clanker.config.settings import Settings

        settings = Settings()
        session_manager = MagicMock()
        console = MagicMock()

        # An empty conversation has nothing to summarize even with force=True.
        with patch("clanker.cli.create_model", return_value=FakeModel()):
            sync_conversation_after_auto_compaction([], session_manager, settings, console)

        session_manager.save_conversation_snapshot.assert_not_called()
        console.print_info.assert_not_called()
