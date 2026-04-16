"""Agent creation using LangChain with SummarizationMiddleware."""

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langgraph.checkpoint.base import BaseCheckpointSaver

from clanker.agent.middleware import multimodal_tool_results
from clanker.agent.prompts import get_system_prompt
from clanker.config import Settings, get_settings, get_default_model, create_llm_from_config
from clanker.logging import get_logger
from clanker.mcp import load_mcp_tools, load_mcp_tools_async
from clanker.tools import ALL_TOOLS

# Module logger
logger = get_logger("agent")


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


def create_model(settings: Settings = None):
    """Create the LLM based on JSON models configuration.

    Args:
        settings: Optional settings (unused, kept for API compatibility).

    Returns:
        Configured LangChain chat model.

    Raises:
        ValueError: If no model is configured.
    """
    default_model = get_default_model()
    if not default_model:
        raise ValueError(
            "No model configured. Run 'clanker' to start the setup wizard, "
            "or use 'clanker model add' to configure a model."
        )

    logger.info("Using model: %s (provider=%s)", default_model.name, default_model.provider)
    return create_llm_from_config(default_model)


def create_agent_graph(
    settings: Settings | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """Create an agent with SummarizationMiddleware.

    Args:
        settings: Optional settings override.
        checkpointer: Optional checkpointer for persistence.

    Returns:
        Compiled agent with automatic summarization.
    """
    settings = settings or get_settings()

    # Get all tools (built-in + MCP)
    all_tools = _get_all_tools(settings)

    # Create model
    model = create_model(settings)

    # Convert percentage to fraction (e.g., 80.0 -> 0.8)
    trigger_fraction = settings.context.summarization_threshold / 100.0
    logger.info("Summarization trigger: %.0f%% of context window", settings.context.summarization_threshold)

    # Create summarization middleware using the same model
    # Uses fraction-based trigger which automatically uses model's context window
    summarization = SummarizationMiddleware(
        model=model,
        trigger=("fraction", trigger_fraction),
        keep=("messages", settings.context.keep_recent_turns * 2),
    )

    # Create agent with middleware
    # - multimodal_tool_results: converts tool results with images to multimodal ToolMessages
    # - summarization: handles context window management
    agent = create_agent(
        model=model,
        tools=all_tools,
        middleware=[multimodal_tool_results, summarization],
        checkpointer=checkpointer,
        system_prompt=get_system_prompt(),
    )

    return agent


async def create_agent_graph_async(
    settings: Settings | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """Create an agent with async MCP tool loading and SummarizationMiddleware.

    Args:
        settings: Optional settings override.
        checkpointer: Optional checkpointer for persistence.

    Returns:
        Tuple of (agent, mcp_client). Keep mcp_client alive while using agent.
    """
    settings = settings or get_settings()

    # Get built-in tools
    tools = list(ALL_TOOLS)
    logger.debug("Loaded %d built-in tools", len(tools))

    # Load MCP tools asynchronously
    mcp_client = None
    if settings.mcp.enabled:
        try:
            mcp_client, mcp_tools = await load_mcp_tools_async(settings)
            tools.extend(mcp_tools)
            logger.info("Loaded %d MCP tools", len(mcp_tools))
        except Exception as e:
            logger.warning("Failed to load MCP tools: %s", e)

    logger.debug("Total tools available: %d", len(tools))

    # Create model
    model = create_model(settings)

    # Convert percentage to fraction (e.g., 80.0 -> 0.8)
    trigger_fraction = settings.context.summarization_threshold / 100.0
    logger.info("Summarization trigger: %.0f%% of context window", settings.context.summarization_threshold)

    # Create summarization middleware using the same model
    # Uses fraction-based trigger which automatically uses model's context window
    summarization = SummarizationMiddleware(
        model=model,
        trigger=("fraction", trigger_fraction),
        keep=("messages", settings.context.keep_recent_turns * 2),
    )

    # Create agent with middleware
    # - multimodal_tool_results: converts tool results with images to multimodal ToolMessages
    # - summarization: handles context window management
    agent = create_agent(
        model=model,
        tools=tools,
        middleware=[multimodal_tool_results, summarization],
        checkpointer=checkpointer,
        system_prompt=get_system_prompt(),
    )

    return agent, mcp_client
