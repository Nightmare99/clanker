"""Agent graph definition using LangGraph."""

import os
from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from clanker.agent.prompts import get_system_prompt
from clanker.agent.state import AgentState
from clanker.config import Settings, get_settings
from clanker.logging import get_logger
from clanker.mcp import load_mcp_tools
from clanker.tools import ALL_TOOLS

# Module logger
logger = get_logger("agent")

# Maximum tool calls per turn to prevent infinite loops
MAX_TOOL_CALLS = 20


def _get_all_tools(settings: Settings) -> list:
    """Get all tools including MCP tools.

    Args:
        settings: Application settings.

    Returns:
        Combined list of built-in and MCP tools.
    """
    tools = list(ALL_TOOLS)
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


def _create_model(settings: Settings):
    """Create the appropriate LLM based on settings."""
    provider = settings.model.provider
    model_name = settings.model.name
    logger.info("Creating model: provider=%s, model=%s", provider, model_name)

    # Build optional kwargs - only include if explicitly set
    optional_kwargs = {}
    if settings.model.temperature is not None:
        optional_kwargs["temperature"] = settings.model.temperature
        logger.debug("Using temperature: %s", settings.model.temperature)
    if settings.model.max_tokens is not None:
        optional_kwargs["max_tokens"] = settings.model.max_tokens
        logger.debug("Using max_tokens: %s", settings.model.max_tokens)

    if provider == "anthropic":
        api_key = settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        # Anthropic requires max_tokens, set default if not provided
        if "max_tokens" not in optional_kwargs:
            optional_kwargs["max_tokens"] = 4096

        # Enable extended thinking if configured
        if settings.model.thinking_enabled:
            optional_kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": settings.model.thinking_budget_tokens,
            }
            logger.info(
                "Extended thinking enabled with budget: %d tokens",
                settings.model.thinking_budget_tokens,
            )

        return ChatAnthropic(
            model=model_name,
            api_key=api_key,
            **optional_kwargs,
        )

    elif provider == "openai":
        api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")
        return ChatOpenAI(
            model=model_name,
            api_key=api_key,
            **optional_kwargs,
        )

    elif provider == "azure":
        api_key = settings.azure_openai_api_key or os.getenv("AZURE_OPENAI_API_KEY")
        endpoint = settings.azure_openai_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        deployment = (
            settings.model.azure.deployment_name
            or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        )
        api_version = settings.model.azure.api_version

        if not api_key:
            raise ValueError("AZURE_OPENAI_API_KEY not set")
        if not endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT not set")
        if not deployment:
            raise ValueError(
                "Azure deployment name not set. Set AZURE_OPENAI_DEPLOYMENT_NAME "
                "or configure model.azure.deployment_name"
            )

        return AzureChatOpenAI(
            azure_endpoint=endpoint,
            azure_deployment=deployment,
            api_version=api_version,
            api_key=api_key,
            **optional_kwargs,
        )

    else:
        raise ValueError(f"Unsupported provider: {provider}")


def _agent_node(state: AgentState, model) -> dict:
    """Main agent reasoning node."""
    messages = state["messages"]
    working_dir = state.get("working_directory", os.getcwd())

    # Add system prompt if not present
    if not messages or not isinstance(messages[0], SystemMessage):
        system_msg = SystemMessage(content=get_system_prompt(working_dir))
        messages = [system_msg] + list(messages)

    response = model.invoke(messages)
    return {"messages": [response]}


def _should_continue(state: AgentState) -> Literal["tools", "end"]:
    """Determine whether to continue with tools or end."""
    messages = state["messages"]
    last_message = messages[-1]

    # Check tool call count to prevent infinite loops
    tool_count = state.get("tool_calls_count", 0)
    if tool_count >= MAX_TOOL_CALLS:
        return "end"

    # Check if the last message has tool calls
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    return "end"


def _increment_tool_count(state: AgentState) -> dict:
    """Increment the tool call counter."""
    current = state.get("tool_calls_count", 0)
    return {"tool_calls_count": current + 1}


def create_agent_graph(
    settings: Settings | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """Create the agent graph.

    Args:
        settings: Optional settings override.
        checkpointer: Optional checkpointer for persistence.

    Returns:
        Compiled LangGraph agent.
    """
    settings = settings or get_settings()

    # Get all tools (built-in + MCP)
    all_tools = _get_all_tools(settings)

    # Create model and bind tools
    model = _create_model(settings)
    model_with_tools = model.bind_tools(all_tools)

    # Create tool node
    tool_node = ToolNode(all_tools)

    # Build the graph
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("agent", lambda state: _agent_node(state, model_with_tools))
    workflow.add_node("tools", tool_node)

    # Set entry point
    workflow.set_entry_point("agent")

    # Add conditional edges
    workflow.add_conditional_edges(
        "agent",
        _should_continue,
        {
            "tools": "tools",
            "end": END,
        },
    )

    # Tools always go back to agent
    workflow.add_edge("tools", "agent")

    # Compile with optional checkpointer
    return workflow.compile(checkpointer=checkpointer)


def create_simple_agent(
    settings: Settings | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """Create a simple agent using LangGraph's prebuilt ReAct agent.

    This is an alternative to create_agent_graph that uses the prebuilt
    create_react_agent for simpler use cases.

    Args:
        settings: Optional settings override.
        checkpointer: Optional checkpointer for persistence.

    Returns:
        Compiled LangGraph agent.
    """
    from langgraph.prebuilt import create_react_agent

    settings = settings or get_settings()
    model = _create_model(settings)
    all_tools = _get_all_tools(settings)

    return create_react_agent(
        model,
        all_tools,
        prompt=get_system_prompt(),
        checkpointer=checkpointer,
    )
