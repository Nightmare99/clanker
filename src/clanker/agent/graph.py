"""Agent creation using LangChain with SummarizationMiddleware."""

import os

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_anthropic import ChatAnthropic
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver

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


def create_model(settings: Settings):
    """Create the appropriate LLM based on configuration.

    This function first checks the JSON-based models config (~/.clanker/models.json).
    If no models are configured there, it falls back to the YAML settings.
    """
    # First, try the new JSON-based model configuration
    default_model = get_default_model()
    if default_model:
        logger.info("Using model from JSON config: %s (provider=%s)",
                   default_model.name, default_model.provider)
        return create_llm_from_config(default_model)

    # Fall back to YAML settings-based configuration
    logger.info("No JSON model config found, using YAML settings")
    return _create_model_from_settings(settings)


def _create_model_from_settings(settings: Settings):
    """Create LLM from YAML settings (legacy approach)."""
    provider = settings.model.provider
    model_name = settings.model.name
    logger.info("Creating model from settings: provider=%s, model=%s", provider, model_name)

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

    elif provider == "azure_anthropic":
        # Azure Foundry Anthropic - Claude models on Microsoft Foundry
        api_key = settings.anthropic_foundry_api_key or os.getenv("ANTHROPIC_FOUNDRY_API_KEY")
        resource = (
            settings.model.azure_anthropic.resource
            or settings.anthropic_foundry_resource
            or os.getenv("ANTHROPIC_FOUNDRY_RESOURCE")
        )
        deployment = settings.model.azure_anthropic.deployment_name or model_name

        if not api_key:
            raise ValueError("ANTHROPIC_FOUNDRY_API_KEY not set")
        if not resource:
            raise ValueError(
                "Azure Foundry resource not set. Set ANTHROPIC_FOUNDRY_RESOURCE "
                "or configure model.azure_anthropic.resource"
            )

        # Construct the Azure Foundry endpoint
        base_url = f"https://{resource}.services.ai.azure.com/anthropic"
        logger.info("Using Azure Foundry Anthropic: resource=%s, deployment=%s", resource, deployment)

        # Anthropic requires max_tokens
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
            model=deployment,
            api_key=api_key,
            base_url=base_url,
            default_headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
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
            stream_usage=True,
            **optional_kwargs,
        )

    else:
        raise ValueError(f"Unsupported provider: {provider}")


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

    # Create summarization middleware using the same model
    summarization = SummarizationMiddleware(
        model=model,  # Use the same configured model
        trigger=("tokens", 8000),  # Trigger when exceeding 8k tokens
        keep=("messages", settings.context.keep_recent_turns * 2),  # Keep recent turns
    )

    # Create agent with middleware
    agent = create_agent(
        model=model,
        tools=all_tools,
        middleware=[summarization],
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

    # Create summarization middleware using the same model
    summarization = SummarizationMiddleware(
        model=model,  # Use the same configured model
        trigger=("tokens", 8000),  # Trigger when exceeding 8k tokens
        keep=("messages", settings.context.keep_recent_turns * 2),  # Keep recent turns
    )

    # Create agent with middleware
    agent = create_agent(
        model=model,
        tools=tools,
        middleware=[summarization],
        checkpointer=checkpointer,
        system_prompt=get_system_prompt(),
    )

    return agent, mcp_client
