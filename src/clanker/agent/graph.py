"""Agent creation using LangChain with RobustSummarizationMiddleware."""

from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver

from clanker.agent.middleware import (
    ToolCallArgTruncationMiddleware,
    ToolResultTruncationMiddleware,
    anthropic_prompt_caching,
    multimodal_tool_results,
)
from clanker.agent.prompts import get_system_prompt
from clanker.agent.summarization import RobustSummarizationMiddleware
from clanker.config import (
    Settings,
    create_llm_from_config,
    get_default_model,
    get_model_by_name,
    get_settings,
)
from clanker.logging import get_logger
from clanker.mcp import load_mcp_tools, load_mcp_tools_async
from clanker.tools import get_tools

# Module logger
logger = get_logger("agent")


def _is_anthropic_model(model: Any) -> bool:
    """Whether *model* will send a native Anthropic-shaped request.

    Only the request WIRE FORMAT determines whether an Anthropic-only field
    like `cache_control` is safe to attach, so this checks the concrete
    `BaseChatModel` class rather than clanker's own `ProviderType` -- GitHub
    Copilot's Claude models still go out as `ChatOpenAI` requests (Copilot
    proxies everything through an OpenAI-compatible endpoint) and must NOT
    get it.
    """
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        return False
    return isinstance(model, ChatAnthropic)


def _cacheable_system_prompt(system_prompt: str, model: Any) -> str | SystemMessage:
    """Mark the system prompt as cacheable for providers that need an explicit opt-in.

    The system prompt is identical on every turn of a session (built once,
    here, at graph-construction time) -- a textbook prompt-caching win. How
    that's actually achieved differs per provider:

    - OpenAI, Azure OpenAI, and GitHub Copilot cache automatically
      server-side for any stable prompt prefix -- no client markup exists or
      is needed, so a plain string is correct as-is.
    - Anthropic requires an explicit `cache_control: {"type": "ephemeral"}`
      breakpoint on a content block, or nothing gets cached and every turn
      pays full input price for the whole system prompt. Wrapping it in a
      `SystemMessage` with a single cache-marked text block is how
      `langchain_anthropic` forwards that breakpoint to the API
      (see `_format_messages` in `langchain_anthropic/chat_models.py`).
    - Ollama is local with no token billing, so caching cost has no meaning
      there; a plain string is left untouched.
    """
    if not _is_anthropic_model(model):
        return system_prompt

    return SystemMessage(
        content=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    )


def _cacheable_tools(tools: list, model: Any) -> list:
    """Mark the tool list as cacheable (Anthropic only -- see `_cacheable_system_prompt`).

    Anthropic caches everything up to and including a `cache_control`
    breakpoint, so marking just the LAST tool definition caches the entire
    tools block -- tool schemas are stable for the whole session (built once,
    here) and can be sizable (every tool's full docstring/parameter schema),
    so this is a second solid, free win alongside the system prompt.

    Builds a COPY of only the last tool with the marker attached in its
    `extras` (the field `langchain_anthropic` forwards `cache_control` from,
    see `convert_to_anthropic_tool`) -- never mutates the shared, process-
    wide tool objects from `get_tools()`, since those exact instances are
    reused across every graph build in this process, including any for
    other (non-Anthropic) models running in the same session.
    """
    if not tools or not _is_anthropic_model(model):
        return tools

    from langchain_core.tools import BaseTool

    *rest, last_tool = tools
    if not isinstance(last_tool, BaseTool):
        # A raw dict/callable tool spec (not a BaseTool instance) has no
        # matching safe copy-and-mark path -- leave the list untouched
        # rather than risk breaking it.
        return tools

    extras = dict(last_tool.extras) if last_tool.extras else {}
    extras["cache_control"] = {"type": "ephemeral"}
    marked_tool = last_tool.model_copy(update={"extras": extras})
    return [*rest, marked_tool]


def _get_all_tools(settings: Settings) -> list:
    """Get all tools including MCP tools.

    Args:
        settings: Application settings.

    Returns:
        Combined list of built-in and MCP tools.
    """
    tools = get_tools()
    logger.debug("Loaded %d built-in tools", len(tools))

    # Load MCP tools if enabled
    if settings.mcp.enabled:
        try:
            mcp_tools = load_mcp_tools(settings)
            tools.extend(mcp_tools)
            logger.info("Loaded %d MCP tools", len(mcp_tools))
        except Exception as e:
            # Don't fail if MCP loading fails - just use built-in tools
            logger.warning("Failed to load MCP tools: %s", e)

    logger.debug("Total tools available: %d", len(tools))
    return tools


def create_model(settings: Settings = None, model_name: str | None = None):
    """Create the LLM based on JSON models configuration.

    Args:
        settings: Optional settings (unused, kept for API compatibility).
        model_name: Optional model name to use. If provided, looks up the
                    model by name in ~/.clanker/models.json. Falls back to
                    the default model if None or the name is not found.

    Returns:
        Configured LangChain chat model.

    Raises:
        ValueError: If no model is configured.
    """
    if model_name:
        chosen = get_model_by_name(model_name)
        if chosen:
            logger.info("Using explicitly configured model: %s (provider=%s)", chosen.name, chosen.provider)
        else:
            logger.warning("Model '%s' not found in config, falling back to default", model_name)
            chosen = get_default_model()
    else:
        chosen = get_default_model()

    if not chosen:
        raise ValueError(
            "No model configured. Run 'clanker' to start the setup wizard, "
            "or use 'clanker model add' to configure a model."
        )

    logger.info("Using model: %s (provider=%s)", chosen.name, chosen.provider)
    return create_llm_from_config(chosen)


def create_agent_graph(
    settings: Settings | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    tools: list | None = None,
    middleware: list | None = None,
    system_prompt: str | None = None,
    model_name: str | None = None,
    working_directory: str | None = None,
    user_query: str | None = None,
):
    """Create an agent with SummarizationMiddleware.

    Args:
        settings: Optional settings override.
        checkpointer: Optional checkpointer for persistence.
        tools: Optional list of tools override.
        middleware: Optional list of middleware override.
        system_prompt: Optional system prompt override. When None, the
                       default prompt is built via `get_system_prompt`,
                       passing `working_directory`/`user_query` through so
                       it can inject the `# ENVIRONMENT` block and relevant
                       workspace memories.
        model_name: Optional model name to use. If provided, looks up the
                    model by name instead of using the default.
        working_directory: Current working directory, forwarded to
                    `get_system_prompt` (ignored if `system_prompt` is set).
        user_query: The user's latest message, forwarded to
                    `get_system_prompt` for relevance-matched memory
                    injection (ignored if `system_prompt` is set).

    Returns:
        Compiled agent with automatic summarization.
    """
    settings = settings or get_settings()

    # Get all tools (built-in + MCP)
    all_tools = tools if tools is not None else _get_all_tools(settings)

    # Create model
    model = create_model(settings, model_name=model_name)

    # Convert percentage to fraction (e.g., 80.0 -> 0.8)
    trigger_fraction = settings.context.summarization_threshold / 100.0
    logger.info("Summarization trigger: %.0f%% of context window", settings.context.summarization_threshold)

    if middleware is None:
        # Create summarization middleware using the same model
        # Uses fraction-based trigger which automatically uses model's context window
        summarization = RobustSummarizationMiddleware(
            model=model,
            trigger=("fraction", trigger_fraction),
            keep=("messages", settings.context.keep_recent_turns * 2),
        )

        # Cap oversized tool results at the tool boundary so a single large result
        # cannot overflow the context window even within summarization's kept window.
        tool_truncation = ToolResultTruncationMiddleware(
            max_tokens=settings.context.max_tool_result_tokens,
        )

        # Cap oversized tool-call ARGUMENTS on the request path so accumulated large
        # writes/edits cannot bloat the request past a proxy's HTTP body-byte limit
        # (a common cause of 413 that the token-based summarization trigger misses).
        tool_call_arg_truncation = ToolCallArgTruncationMiddleware(
            max_tokens=settings.context.max_tool_call_arg_tokens,
        )

        middleware = [
            tool_truncation,
            multimodal_tool_results,
            summarization,
            tool_call_arg_truncation,
            anthropic_prompt_caching,
        ]

    resolved_system_prompt = system_prompt if system_prompt is not None else get_system_prompt(
        working_directory=working_directory, user_query=user_query
    )

    # Create agent with middleware
    # Order matters: first = outermost, last = innermost on the request path.
    agent = create_agent(
        model=model,
        tools=_cacheable_tools(all_tools, model),
        middleware=middleware,
        checkpointer=checkpointer,
        system_prompt=_cacheable_system_prompt(resolved_system_prompt, model),
    )

    return agent


async def create_agent_graph_async(
    settings: Settings | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    tools: list | None = None,
    middleware: list | None = None,
    system_prompt: str | None = None,
    model_name: str | None = None,
    working_directory: str | None = None,
    user_query: str | None = None,
):
    """Create an agent with async MCP tool loading and SummarizationMiddleware.

    Args:
        settings: Optional settings override.
        checkpointer: Optional checkpointer for persistence.
        tools: Optional list of tools override.
        middleware: Optional list of middleware override.
        system_prompt: Optional system prompt override. When None, the
                       default prompt is built via `get_system_prompt`,
                       passing `working_directory`/`user_query` through so
                       it can inject the `# ENVIRONMENT` block and relevant
                       workspace memories.
        model_name: Optional model name to use. If provided, looks up the
                    model by name instead of using the default.
        working_directory: Current working directory, forwarded to
                    `get_system_prompt` (ignored if `system_prompt` is set).
        user_query: The user's latest message, forwarded to
                    `get_system_prompt` for relevance-matched memory
                    injection (ignored if `system_prompt` is set).

    Returns:
        Tuple of (agent, mcp_client). Keep mcp_client alive while using agent.
    """
    settings = settings or get_settings()

    # Get tools
    mcp_client = None
    if tools is not None:
        all_tools = tools
    else:
        # Get built-in tools
        all_tools = get_tools()
        logger.debug("Loaded %d built-in tools", len(all_tools))

        # Load MCP tools asynchronously
        if settings.mcp.enabled:
            try:
                mcp_client, mcp_tools = await load_mcp_tools_async(settings)
                all_tools.extend(mcp_tools)
                logger.info("Loaded %d MCP tools", len(mcp_tools))
            except Exception as e:
                logger.warning("Failed to load MCP tools: %s", e)

    logger.debug("Total tools available: %d", len(all_tools))

    # Create model
    model = create_model(settings, model_name=model_name)

    # Convert percentage to fraction (e.g., 80.0 -> 0.8)
    trigger_fraction = settings.context.summarization_threshold / 100.0
    logger.info("Summarization trigger: %.0f%% of context window", settings.context.summarization_threshold)

    if middleware is None:
        # Create summarization middleware using the same model
        # Uses fraction-based trigger which automatically uses model's context window
        summarization = RobustSummarizationMiddleware(
            model=model,
            trigger=("fraction", trigger_fraction),
            keep=("messages", settings.context.keep_recent_turns * 2),
        )

        # Cap oversized tool results at the tool boundary so a single large result
        # cannot overflow the context window even within summarization's kept window.
        tool_truncation = ToolResultTruncationMiddleware(
            max_tokens=settings.context.max_tool_result_tokens,
        )

        # Cap oversized tool-call ARGUMENTS on the request path so accumulated large
        # writes/edits cannot bloat the request past a proxy's HTTP body-byte limit
        # (a common cause of 413 that the token-based summarization trigger misses).
        tool_call_arg_truncation = ToolCallArgTruncationMiddleware(
            max_tokens=settings.context.max_tool_call_arg_tokens,
        )

        middleware = [
            tool_truncation,
            multimodal_tool_results,
            summarization,
            tool_call_arg_truncation,
            anthropic_prompt_caching,
        ]

    resolved_system_prompt = system_prompt if system_prompt is not None else get_system_prompt(
        working_directory=working_directory, user_query=user_query
    )

    # Create agent with middleware
    # Order matters: first = outermost, last = innermost on the request path.
    agent = create_agent(
        model=model,
        tools=_cacheable_tools(all_tools, model),
        middleware=middleware,
        checkpointer=checkpointer,
        system_prompt=_cacheable_system_prompt(resolved_system_prompt, model),
    )

    return agent, mcp_client
