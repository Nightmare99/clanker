"""Tests for Anthropic prompt-cache breakpoints: system prompt, tools, and the
newest message of every model call.

The system prompt and tools list are identical on every turn of a session
(built once at graph-construction time) -- a textbook stable prefix. The
conversation history grows every turn but shares a common prefix with the
previous call, which is exactly what the per-call "cache the last message"
breakpoint (`AnthropicPromptCachingMiddleware`) targets. OpenAI/Azure
OpenAI/GitHub Copilot cache automatically server-side for any stable prefix
-- no client markup exists for it, so those must always be left untouched.
Anthropic requires an explicit `cache_control` breakpoint on a content block,
or nothing gets cached at all.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


class TestCacheableSystemPrompt:
    def test_anthropic_model_gets_cache_control_breakpoint(self) -> None:
        from langchain_anthropic import ChatAnthropic

        from clanker.agent.graph import _cacheable_system_prompt

        model = ChatAnthropic(api_key="fake-key", model="claude-sonnet-4-20250514")
        result = _cacheable_system_prompt("You are a helpful assistant.", model)

        assert isinstance(result, SystemMessage)
        assert result.content == [
            {
                "type": "text",
                "text": "You are a helpful assistant.",
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def test_openai_model_unaffected(self) -> None:
        from langchain_openai import ChatOpenAI

        from clanker.agent.graph import _cacheable_system_prompt

        model = ChatOpenAI(api_key="fake-key", model="gpt-4o")
        result = _cacheable_system_prompt("You are a helpful assistant.", model)

        assert result == "You are a helpful assistant."

    def test_azure_openai_model_unaffected(self) -> None:
        from langchain_openai import AzureChatOpenAI

        from clanker.agent.graph import _cacheable_system_prompt

        model = AzureChatOpenAI(
            api_key="fake-key",
            azure_endpoint="https://example.openai.azure.com",
            azure_deployment="gpt-4o",
            api_version="2024-10-21",
        )
        result = _cacheable_system_prompt("You are a helpful assistant.", model)

        assert result == "You are a helpful assistant."

    def test_copilot_style_openai_model_unaffected(self) -> None:
        """GitHub Copilot routes through ChatOpenAI regardless of the backing
        model (even Claude) -- the wire format is OpenAI-shaped, so it must
        never get an Anthropic-only cache_control field attached."""
        from langchain_openai import ChatOpenAI

        from clanker.agent.graph import _cacheable_system_prompt

        model = ChatOpenAI(
            api_key="fake-key", model="claude-sonnet-4", base_url="https://copilot.example/v1"
        )
        result = _cacheable_system_prompt("You are a helpful assistant.", model)

        assert result == "You are a helpful assistant."

    def test_unrecognized_model_type_unaffected(self) -> None:
        from clanker.agent.graph import _cacheable_system_prompt

        result = _cacheable_system_prompt("You are a helpful assistant.", MagicMock())
        assert result == "You are a helpful assistant."


class TestGraphAppliesCaching:
    """create_agent_graph/_async actually pass the cache-marked prompt through."""

    def test_create_agent_graph_passes_wrapped_prompt_for_anthropic(self) -> None:
        from langchain_anthropic import ChatAnthropic

        from clanker.agent.graph import create_agent_graph
        from clanker.config.settings import Settings

        settings = Settings()
        model = ChatAnthropic(api_key="fake-key", model="claude-sonnet-4-20250514")
        model.profile = {"max_input_tokens": 200_000}

        with patch("clanker.agent.graph.create_model", return_value=model), \
             patch("clanker.agent.graph.create_agent") as mock_create_agent:
            mock_create_agent.return_value = MagicMock()
            create_agent_graph(settings, tools=[], system_prompt="Be concise.")

        _, kwargs = mock_create_agent.call_args
        assert isinstance(kwargs["system_prompt"], SystemMessage)
        assert kwargs["system_prompt"].content[0]["cache_control"] == {"type": "ephemeral"}
        assert kwargs["system_prompt"].content[0]["text"] == "Be concise."

    async def test_create_agent_graph_async_passes_plain_string_for_openai(self) -> None:
        from langchain_openai import ChatOpenAI

        from clanker.agent.graph import create_agent_graph_async
        from clanker.config.settings import Settings

        settings = Settings()
        model = ChatOpenAI(api_key="fake-key", model="gpt-4o")

        with patch("clanker.agent.graph.create_model", return_value=model), \
             patch("clanker.agent.graph.create_agent") as mock_create_agent:
            mock_create_agent.return_value = MagicMock()
            await create_agent_graph_async(settings, tools=[], system_prompt="Be concise.")

        _, kwargs = mock_create_agent.call_args
        assert kwargs["system_prompt"] == "Be concise."

    def test_create_agent_graph_includes_caching_middleware_by_default(self) -> None:
        from langchain_anthropic import ChatAnthropic

        from clanker.agent.graph import create_agent_graph
        from clanker.agent.middleware import AnthropicPromptCachingMiddleware
        from clanker.config.settings import Settings

        settings = Settings()
        model = ChatAnthropic(api_key="fake-key", model="claude-sonnet-4-20250514")
        model.profile = {"max_input_tokens": 200_000}

        with patch("clanker.agent.graph.create_model", return_value=model), \
             patch("clanker.agent.graph.create_agent") as mock_create_agent:
            mock_create_agent.return_value = MagicMock()
            create_agent_graph(settings, tools=[])

        _, kwargs = mock_create_agent.call_args
        assert any(
            isinstance(mw, AnthropicPromptCachingMiddleware) for mw in kwargs["middleware"]
        )


class TestCacheableTools:
    def test_anthropic_marks_only_last_tool(self) -> None:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.tools import tool

        from clanker.agent.graph import _cacheable_tools

        @tool
        def foo(x: int) -> str:
            """Does foo."""
            return str(x)

        @tool
        def bar(y: int) -> str:
            """Does bar."""
            return str(y)

        model = ChatAnthropic(api_key="fake-key", model="claude-sonnet-4-20250514")
        marked = _cacheable_tools([foo, bar], model)

        assert marked[0] is foo  # untouched, same object
        assert marked[1] is not bar  # a copy
        assert marked[1].extras == {"cache_control": {"type": "ephemeral"}}

    def test_never_mutates_the_shared_global_tool_object(self) -> None:
        """get_tools() returns the SAME instances on every call/session --
        marking must never leak cache_control onto them permanently."""
        from langchain_anthropic import ChatAnthropic
        from langchain_core.tools import tool

        from clanker.agent.graph import _cacheable_tools

        @tool
        def baz(z: int) -> str:
            """Does baz."""
            return str(z)

        model = ChatAnthropic(api_key="fake-key", model="claude-sonnet-4-20250514")
        _cacheable_tools([baz], model)

        assert baz.extras is None

    def test_preserves_existing_extras(self) -> None:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.tools import tool

        from clanker.agent.graph import _cacheable_tools

        @tool
        def qux(w: int) -> str:
            """Does qux."""
            return str(w)

        qux.extras = {"some_other_field": True}
        model = ChatAnthropic(api_key="fake-key", model="claude-sonnet-4-20250514")
        marked = _cacheable_tools([qux], model)

        assert marked[0].extras == {
            "some_other_field": True,
            "cache_control": {"type": "ephemeral"},
        }

    def test_openai_leaves_tools_list_untouched(self) -> None:
        from langchain_core.tools import tool
        from langchain_openai import ChatOpenAI

        from clanker.agent.graph import _cacheable_tools

        @tool
        def foo(x: int) -> str:
            """Does foo."""
            return str(x)

        model = ChatOpenAI(api_key="fake-key", model="gpt-4o")
        tools = [foo]
        assert _cacheable_tools(tools, model) is tools

    def test_empty_tools_list(self) -> None:
        from langchain_anthropic import ChatAnthropic

        from clanker.agent.graph import _cacheable_tools

        model = ChatAnthropic(api_key="fake-key", model="claude-sonnet-4-20250514")
        assert _cacheable_tools([], model) == []


class TestMarkMessageCacheable:
    def test_string_content_wrapped_and_marked(self) -> None:
        from clanker.agent.middleware import _mark_message_cacheable

        msg = HumanMessage(content="hello there")
        marked = _mark_message_cacheable(msg)

        assert marked.content == [
            {"type": "text", "text": "hello there", "cache_control": {"type": "ephemeral"}}
        ]
        assert msg.content == "hello there"  # original untouched

    def test_empty_string_content_unchanged(self) -> None:
        from clanker.agent.middleware import _mark_message_cacheable

        msg = HumanMessage(content="")
        assert _mark_message_cacheable(msg) is msg

    def test_list_content_only_last_block_marked(self) -> None:
        from clanker.agent.middleware import _mark_message_cacheable

        msg = HumanMessage(
            content=[{"type": "text", "text": "part1"}, {"type": "text", "text": "part2"}]
        )
        marked = _mark_message_cacheable(msg)

        assert marked.content[0] == {"type": "text", "text": "part1"}
        assert marked.content[1] == {
            "type": "text",
            "text": "part2",
            "cache_control": {"type": "ephemeral"},
        }

    def test_tool_message_content_marked(self) -> None:
        """cache_control on a tool_result sub-block is hoisted by
        langchain_anthropic onto the tool_result block itself -- same
        marking mechanism works uniformly for ToolMessage."""
        from clanker.agent.middleware import _mark_message_cacheable

        msg = ToolMessage(content="tool output text", tool_call_id="abc123")
        marked = _mark_message_cacheable(msg)

        assert marked.content == [
            {"type": "text", "text": "tool output text", "cache_control": {"type": "ephemeral"}}
        ]
        assert marked.tool_call_id == "abc123"

    def test_empty_list_content_unchanged(self) -> None:
        from clanker.agent.middleware import _mark_message_cacheable

        msg = AIMessage(content=[])
        assert _mark_message_cacheable(msg) is msg


class TestAnthropicPromptCachingMiddleware:
    def test_marks_last_message_for_anthropic(self) -> None:
        from langchain.agents.middleware.types import ModelRequest
        from langchain_anthropic import ChatAnthropic

        from clanker.agent.middleware import anthropic_prompt_caching

        model = ChatAnthropic(api_key="fake-key", model="claude-sonnet-4-20250514")
        request = ModelRequest(
            model=model,
            messages=[HumanMessage(content="m1"), HumanMessage(content="m2")],
        )

        captured = {}
        anthropic_prompt_caching.wrap_model_call(request, lambda r: captured.setdefault("req", r))

        new_messages = captured["req"].messages
        assert new_messages[0] is request.messages[0]  # earlier message untouched
        assert new_messages[1].content[-1]["cache_control"] == {"type": "ephemeral"}

    async def test_awrap_model_call_marks_last_message(self) -> None:
        from langchain.agents.middleware.types import ModelRequest
        from langchain_anthropic import ChatAnthropic

        from clanker.agent.middleware import anthropic_prompt_caching

        model = ChatAnthropic(api_key="fake-key", model="claude-sonnet-4-20250514")
        request = ModelRequest(model=model, messages=[HumanMessage(content="m1")])

        captured = {}

        async def handler(r):
            captured["req"] = r
            return "ok"

        await anthropic_prompt_caching.awrap_model_call(request, handler)

        assert captured["req"].messages[0].content[-1]["cache_control"] == {
            "type": "ephemeral"
        }

    def test_non_anthropic_request_passed_through_unchanged(self) -> None:
        from langchain.agents.middleware.types import ModelRequest
        from langchain_openai import ChatOpenAI

        from clanker.agent.middleware import anthropic_prompt_caching

        model = ChatOpenAI(api_key="fake-key", model="gpt-4o")
        request = ModelRequest(model=model, messages=[HumanMessage(content="m1")])

        captured = {}
        anthropic_prompt_caching.wrap_model_call(request, lambda r: captured.setdefault("req", r))

        assert captured["req"] is request

    def test_empty_messages_passed_through_unchanged(self) -> None:
        from langchain.agents.middleware.types import ModelRequest
        from langchain_anthropic import ChatAnthropic

        from clanker.agent.middleware import anthropic_prompt_caching

        model = ChatAnthropic(api_key="fake-key", model="claude-sonnet-4-20250514")
        request = ModelRequest(model=model, messages=[])

        captured = {}
        anthropic_prompt_caching.wrap_model_call(request, lambda r: captured.setdefault("req", r))

        assert captured["req"] is request
