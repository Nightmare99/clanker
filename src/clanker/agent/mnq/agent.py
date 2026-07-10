"""Agent creation and execution logic for MNQ mode."""

from typing import Any, Dict, List

from langchain.agents import create_agent
from langgraph.checkpoint.base import BaseCheckpointSaver

from clanker.agent.middleware import (
    ToolCallArgTruncationMiddleware,
    ToolResultTruncationMiddleware,
    multimodal_tool_results,
)
from clanker.agent.mnq.roles import get_role_prompt
from clanker.agent.mnq.tools import get_board_tools
from clanker.agent.summarization import RobustSummarizationMiddleware
from clanker.config import Settings, get_default_model, get_models_config, create_llm_from_config
from clanker.logging import get_logger
from clanker.mcp import load_mcp_tools
from clanker.tools import get_tools
from clanker.ui.streaming import stream_agent_response_sync

logger = get_logger("agent.mnq")


def resolve_model_for_role(role: str, settings: Settings) -> Any:
    """Resolve the model configuration to use for a specific role.

    Args:
        role: The role name.
        settings: Application settings containing MNQ configurations.

    Returns:
        A LangChain ChatModel instance.
    """
    # 1. Get mapped model/tier name from settings
    role_model = getattr(settings.mnq.models, role, "strong")

    # 2. Load configured models
    models_cfg = get_models_config()

    # 3. If mapped value matches a configured model name exactly, use it
    for model in models_cfg.models:
        if model.name.lower() == role_model.lower():
            logger.info("Mapped role '%s' to model name '%s'", role, model.name)
            return create_llm_from_config(model)

    # 4. Handle tiers ("strong" / "mid")
    default_model = get_default_model()
    if not default_model:
        raise ValueError("No default model is configured.")

    if role_model == "mid":
        # Search for a mid-tier/cheaper model (e.g. Flash, Haiku, Mini)
        for model in models_cfg.models:
            name_lower = model.name.lower()
            model_id_lower = (model.model or "").lower()
            if any(x in name_lower or x in model_id_lower for x in ["mini", "flash", "haiku", "3.5-turbo"]):
                logger.info("Mapped role '%s' to mid-tier model '%s'", role, model.name)
                return create_llm_from_config(model)

    logger.info("Mapped role '%s' to default model '%s' (fallback)", role, default_model.name)
    return create_llm_from_config(default_model)


def create_role_agent_graph(
    role: str,
    system_prompt: str,
    settings: Settings,
    checkpointer: BaseCheckpointSaver | None = None,
) -> Any:
    """Create a LangGraph agent specifically for a given MNQ role.

    Args:
        role: The role name.
        system_prompt: The system prompt containing task context.
        settings: Application settings.
        checkpointer: Optional persistence checkpoint saver.

    Returns:
        Compiled LangGraph agent.
    """
    # Resolve the correct LLM model for this role
    model = resolve_model_for_role(role, settings)

    # Gather standard tools
    tools = get_tools()

    # Load MCP tools if enabled
    if settings.mcp.enabled:
        try:
            mcp_tools = load_mcp_tools(settings)
            tools.extend(mcp_tools)
        except Exception as e:
            logger.warning("Failed to load MCP tools for role '%s': %s", role, e)

    # Gather task board tools
    board_tools = get_board_tools()
    tools.extend(board_tools)

    # Context management middleware
    trigger_fraction = settings.context.summarization_threshold / 100.0
    summarization = RobustSummarizationMiddleware(
        model=model,
        trigger=("fraction", trigger_fraction),
        keep=("messages", settings.context.keep_recent_turns * 2),
    )

    tool_truncation = ToolResultTruncationMiddleware(
        max_tokens=settings.context.max_tool_result_tokens,
    )

    tool_call_arg_truncation = ToolCallArgTruncationMiddleware(
        max_tokens=settings.context.max_tool_call_arg_tokens,
    )

    # Create the agent
    agent = create_agent(
        model=model,
        tools=tools,
        middleware=[tool_truncation, multimodal_tool_results, summarization, tool_call_arg_truncation],
        checkpointer=checkpointer,
        system_prompt=system_prompt,
    )

    return agent


def run_role_agent(
    role: str,
    task_description: str,
    board_summary: str,
    settings: Settings,
    checkpointer: BaseCheckpointSaver | None,
    config: Dict[str, Any],
    console: Any,
) -> Any:
    """Instantiate and run a role-scoped agent with the unified streaming UI.

    Args:
        role: The role to run.
        task_description: Instructions/details of the task.
        board_summary: Formatted string of current task board state.
        settings: Application settings.
        checkpointer: SQLite checkpointer.
        config: Run configuration (e.g. thread_id).
        console: CLI console helper.

    Returns:
        StreamResult of the run.
    """
    system_prompt = get_role_prompt(role, board_summary)
    graph = create_role_agent_graph(role, system_prompt, settings, checkpointer)

    state = {
        "messages": [{"role": "user", "content": task_description}],
    }

    return stream_agent_response_sync(
        settings=settings,
        checkpointer=checkpointer,
        state=state,
        config=config,
        console=console,
        graph=graph,
    )
