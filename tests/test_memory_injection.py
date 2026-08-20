"""Tests for wiring working_directory/user_query through to get_system_prompt().

get_system_prompt() has real logic to inject the # ENVIRONMENT block and
relevance-matched workspace memories (see prompts.py), but only when given
working_directory/user_query. Previously, create_agent_graph/_async always
called get_system_prompt() with no arguments, so that logic was dead code at
runtime -- the agent never saw its own working directory or any memories
unless it proactively called `recall` itself. These tests lock in that the
real call chain (stream_agent_response_async -> create_agent_graph_async ->
get_system_prompt) now actually threads those two values through.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


class TestExtractUserQuery:
    def test_plain_string_content(self) -> None:
        from clanker.ui.streaming import _extract_user_query

        messages = [HumanMessage(content="fix the login bug")]
        assert _extract_user_query(messages) == "fix the login bug"

    def test_uses_newest_human_message(self) -> None:
        from clanker.ui.streaming import _extract_user_query

        messages = [
            HumanMessage(content="first question"),
            AIMessage(content="answer"),
            HumanMessage(content="second question"),
        ]
        assert _extract_user_query(messages) == "second question"

    def test_multimodal_content_extracts_text_blocks_only(self) -> None:
        from clanker.ui.streaming import _extract_user_query

        messages = [
            HumanMessage(content=[
                {"type": "text", "text": "what is this image"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,xyz"}},
            ])
        ]
        assert _extract_user_query(messages) == "what is this image"

    def test_no_human_message_returns_none(self) -> None:
        from clanker.ui.streaming import _extract_user_query

        assert _extract_user_query([AIMessage(content="hi"), ToolMessage(content="x", tool_call_id="1")]) is None

    def test_empty_messages_returns_none(self) -> None:
        from clanker.ui.streaming import _extract_user_query

        assert _extract_user_query([]) is None

    def test_empty_string_content_returns_none(self) -> None:
        from clanker.ui.streaming import _extract_user_query

        assert _extract_user_query([HumanMessage(content="")]) is None


class TestCreateAgentGraphForwardsContext:
    """create_agent_graph/_async must forward working_directory/user_query
    into get_system_prompt() when no explicit system_prompt override is given."""

    def test_create_agent_graph_forwards_context(self) -> None:
        from clanker.agent.graph import create_agent_graph
        from clanker.config.settings import Settings

        settings = Settings()
        model = MagicMock()
        model.profile = {"max_input_tokens": 100_000}

        with patch("clanker.agent.graph.create_model", return_value=model), \
             patch("clanker.agent.graph.create_agent") as mock_create_agent, \
             patch("clanker.agent.graph.get_system_prompt", return_value="prompt") as mock_get_prompt:
            mock_create_agent.return_value = MagicMock()
            create_agent_graph(
                settings, tools=[],
                working_directory="/workspace/project",
                user_query="where is the auth handler",
            )

        mock_get_prompt.assert_called_once_with(
            working_directory="/workspace/project", user_query="where is the auth handler"
        )

    async def test_create_agent_graph_async_forwards_context(self) -> None:
        from clanker.agent.graph import create_agent_graph_async
        from clanker.config.settings import Settings

        settings = Settings()
        model = MagicMock()
        model.profile = {"max_input_tokens": 100_000}

        with patch("clanker.agent.graph.create_model", return_value=model), \
             patch("clanker.agent.graph.create_agent") as mock_create_agent, \
             patch("clanker.agent.graph.get_system_prompt", return_value="prompt") as mock_get_prompt:
            mock_create_agent.return_value = MagicMock()
            await create_agent_graph_async(
                settings, tools=[],
                working_directory="/workspace/project",
                user_query="where is the auth handler",
            )

        mock_get_prompt.assert_called_once_with(
            working_directory="/workspace/project", user_query="where is the auth handler"
        )

    def test_explicit_system_prompt_override_skips_get_system_prompt(self) -> None:
        """An explicit system_prompt (e.g. a subagent's own prompt) must not
        be clobbered by working_directory/user_query injection."""
        from clanker.agent.graph import create_agent_graph
        from clanker.config.settings import Settings

        settings = Settings()
        model = MagicMock()
        model.profile = {"max_input_tokens": 100_000}

        with patch("clanker.agent.graph.create_model", return_value=model), \
             patch("clanker.agent.graph.create_agent") as mock_create_agent, \
             patch("clanker.agent.graph.get_system_prompt") as mock_get_prompt:
            mock_create_agent.return_value = MagicMock()
            create_agent_graph(
                settings, tools=[], system_prompt="a fixed override prompt",
                working_directory="/workspace/project",
            )

        mock_get_prompt.assert_not_called()
        _, kwargs = mock_create_agent.call_args
        assert kwargs["system_prompt"] == "a fixed override prompt"


class TestStreamingForwardsContext:
    """stream_agent_response_async pulls working_directory/user_query out of
    the turn's own state dict and forwards them to create_agent_graph_async."""

    async def test_forwards_working_directory_and_user_query(self) -> None:
        from clanker.ui.streaming import stream_agent_response_async

        mock_graph = MagicMock()

        async def astream_events(state, config, version):
            return
            yield  # pragma: no cover - empty async generator

        mock_graph.astream_events = astream_events
        mock_graph.aget_state = AsyncMock(
            return_value=MagicMock(values={"compaction_count": 0})
        )

        with patch(
            "clanker.agent.create_agent_graph_async",
            new_callable=AsyncMock,
            return_value=(mock_graph, None),
        ) as mock_create_graph, patch(
            "clanker.ui.streaming._teardown_live_displays"
        ), patch(
            "clanker.ui.streaming._heal_orphaned_tool_calls", new_callable=AsyncMock
        ):
            await stream_agent_response_async(
                settings=MagicMock(),
                checkpointer=None,
                state={
                    "messages": [HumanMessage(content="where is the auth handler")],
                    "working_directory": "/workspace/project",
                },
                config={"configurable": {"thread_id": "test"}},
                console=MagicMock(),
            )

        _, kwargs = mock_create_graph.call_args
        assert kwargs["working_directory"] == "/workspace/project"
        assert kwargs["user_query"] == "where is the auth handler"

    async def test_missing_working_directory_forwards_none(self) -> None:
        from clanker.ui.streaming import stream_agent_response_async

        mock_graph = MagicMock()

        async def astream_events(state, config, version):
            return
            yield  # pragma: no cover

        mock_graph.astream_events = astream_events
        mock_graph.aget_state = AsyncMock(
            return_value=MagicMock(values={"compaction_count": 0})
        )

        with patch(
            "clanker.agent.create_agent_graph_async",
            new_callable=AsyncMock,
            return_value=(mock_graph, None),
        ) as mock_create_graph, patch(
            "clanker.ui.streaming._teardown_live_displays"
        ), patch(
            "clanker.ui.streaming._heal_orphaned_tool_calls", new_callable=AsyncMock
        ):
            await stream_agent_response_async(
                settings=MagicMock(),
                checkpointer=None,
                state={"messages": []},
                config={"configurable": {"thread_id": "test"}},
                console=MagicMock(),
            )

        _, kwargs = mock_create_graph.call_args
        assert kwargs["working_directory"] is None
        assert kwargs["user_query"] is None
