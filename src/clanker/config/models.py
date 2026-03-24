"""Model configuration management using JSON."""

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from clanker.logging import get_logger

logger = get_logger("config.models")

# Models config file path
MODELS_CONFIG_PATH = Path.home() / ".clanker" / "models.json"

ProviderType = Literal["AzureOpenAI", "OpenAI", "Anthropic", "Ollama"]


class ModelConfig(BaseModel):
    """Configuration for a single model."""

    name: str = Field(description="Display name for the model")
    provider: ProviderType = Field(description="LLM provider type")
    api_key: str | None = Field(default=None, description="API key for the provider")
    base_url: str | None = Field(default=None, description="Base URL for the API")
    model: str | None = Field(default=None, description="Model identifier (e.g., gpt-4o, claude-sonnet-4)")

    # Azure-specific
    deployment_name: str | None = Field(default=None, description="Azure deployment name")
    api_version: str | None = Field(default=None, description="Azure API version")

    # Token limits
    max_tokens: int | None = Field(default=None, description="Maximum tokens for response")

    # Extended thinking (Anthropic)
    thinking_enabled: bool = Field(default=False, description="Enable extended thinking mode")
    thinking_budget_tokens: int = Field(default=10000, description="Token budget for thinking")

    # Reasoning effort (Azure OpenAI o1/o3 models)
    reasoning_effort: str | None = Field(default=None, description="Reasoning effort: low, medium, high")

    class Config:
        extra = "allow"  # Allow additional provider-specific fields


class ModelsConfig(BaseModel):
    """Configuration for all models."""

    models: list[ModelConfig] = Field(default_factory=list)
    default: str | None = Field(default=None, description="Name of the default model")


def get_models_config() -> ModelsConfig:
    """Load models configuration from JSON file."""
    if not MODELS_CONFIG_PATH.exists():
        logger.info("No models config found, returning empty config")
        return ModelsConfig()

    try:
        with open(MODELS_CONFIG_PATH) as f:
            data = json.load(f)
        return ModelsConfig(**data)
    except (json.JSONDecodeError, Exception) as e:
        logger.error("Failed to load models config: %s", e)
        return ModelsConfig()


def save_models_config(config: ModelsConfig) -> None:
    """Save models configuration to JSON file."""
    MODELS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(MODELS_CONFIG_PATH, "w") as f:
        json.dump(config.model_dump(), f, indent=2)

    logger.info("Saved models config to %s", MODELS_CONFIG_PATH)


def get_model_by_name(name: str) -> ModelConfig | None:
    """Get a model configuration by its name."""
    config = get_models_config()
    for model in config.models:
        if model.name.lower() == name.lower():
            return model
    return None


def get_default_model() -> ModelConfig | None:
    """Get the default model configuration."""
    config = get_models_config()
    if config.default:
        return get_model_by_name(config.default)
    if config.models:
        return config.models[0]
    return None


def set_default_model(name: str) -> bool:
    """Set the default model by name."""
    config = get_models_config()

    # Check if model exists
    model = get_model_by_name(name)
    if not model:
        return False

    config.default = model.name
    save_models_config(config)
    return True


def list_model_names() -> list[str]:
    """Get list of all configured model names."""
    config = get_models_config()
    return [m.name for m in config.models]


def add_model(model: ModelConfig) -> None:
    """Add a new model configuration."""
    config = get_models_config()

    # Remove existing model with same name
    config.models = [m for m in config.models if m.name.lower() != model.name.lower()]
    config.models.append(model)

    # Set as default if first model
    if len(config.models) == 1:
        config.default = model.name

    save_models_config(config)


def remove_model(name: str) -> bool:
    """Remove a model configuration by name."""
    config = get_models_config()
    original_count = len(config.models)
    config.models = [m for m in config.models if m.name.lower() != name.lower()]

    if len(config.models) < original_count:
        # Update default if we removed it
        if config.default and config.default.lower() == name.lower():
            config.default = config.models[0].name if config.models else None
        save_models_config(config)
        return True
    return False


def create_llm_from_config(model_config: ModelConfig):
    """Create a LangChain LLM from model configuration."""
    provider = model_config.provider

    if provider == "OpenAI":
        from langchain_openai import ChatOpenAI

        api_key = model_config.api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(f"API key not set for model '{model_config.name}'")

        kwargs = {}
        if model_config.model:
            kwargs["model"] = model_config.model
        if model_config.base_url:
            kwargs["base_url"] = model_config.base_url

        # Reasoning effort for o1/o3/GPT-5+ models
        if model_config.reasoning_effort:
            kwargs["reasoning_effort"] = model_config.reasoning_effort
            logger.info(
                "Reasoning enabled for %s with effort: %s",
                model_config.name,
                model_config.reasoning_effort,
            )

        # Max tokens if specified
        if model_config.max_tokens:
            kwargs["max_tokens"] = model_config.max_tokens

        # stream_usage enables token counts in streaming responses
        return ChatOpenAI(
            api_key=api_key,
            stream_usage=True,
            **kwargs,
        )

    elif provider == "AzureOpenAI":
        from langchain_openai import AzureChatOpenAI

        api_key = model_config.api_key or os.getenv("AZURE_OPENAI_API_KEY")
        base_url = model_config.base_url or os.getenv("AZURE_OPENAI_ENDPOINT")
        deployment = model_config.deployment_name or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        # Use newer API version that supports stream_options for token usage
        api_version = model_config.api_version or "2024-10-21"

        if not api_key:
            raise ValueError(f"API key not set for model '{model_config.name}'")
        if not base_url:
            raise ValueError(f"Base URL (endpoint) not set for model '{model_config.name}'")
        if not deployment:
            raise ValueError(f"Deployment name not set for model '{model_config.name}'")

        # Don't set temperature - some Azure models (o1, o3, gpt-5) only support default (1)
        # We need to set it to 1 explicitly since LangChain defaults to 0.7
        # stream_usage enables token counts in streaming responses
        kwargs = {
            "azure_endpoint": base_url,
            "azure_deployment": deployment,
            "api_version": api_version,
            "api_key": api_key,
            "temperature": 1,
            "stream_usage": True,
        }

        # Reasoning effort for o1/o3/GPT-5+ models
        if model_config.reasoning_effort:
            kwargs["reasoning_effort"] = model_config.reasoning_effort
            logger.info(
                "Reasoning enabled for %s with effort: %s",
                model_config.name,
                model_config.reasoning_effort,
            )

        # Max tokens if specified
        if model_config.max_tokens:
            kwargs["max_tokens"] = model_config.max_tokens

        return AzureChatOpenAI(**kwargs)

    elif provider == "Anthropic":
        from langchain_anthropic import ChatAnthropic

        api_key = model_config.api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(f"API key not set for model '{model_config.name}'")

        # Determine max_tokens
        if model_config.max_tokens:
            max_tokens = model_config.max_tokens
        elif model_config.thinking_enabled:
            # max_tokens must be > thinking.budget_tokens, add buffer for response
            max_tokens = model_config.thinking_budget_tokens + 16000
        else:
            max_tokens = 4096

        # Validate max_tokens > thinking budget when thinking is enabled
        if model_config.thinking_enabled and max_tokens <= model_config.thinking_budget_tokens:
            raise ValueError(
                f"max_tokens ({max_tokens}) must be greater than thinking_budget_tokens "
                f"({model_config.thinking_budget_tokens})"
            )

        kwargs = {
            "api_key": api_key,
            "max_tokens": max_tokens,
        }
        if model_config.model:
            kwargs["model"] = model_config.model
        if model_config.base_url:
            kwargs["base_url"] = model_config.base_url

        # Extended thinking support
        if model_config.thinking_enabled:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": model_config.thinking_budget_tokens,
            }
            logger.info(
                "Extended thinking enabled for %s with budget: %d tokens (max_tokens: %d)",
                model_config.name,
                model_config.thinking_budget_tokens,
                max_tokens,
            )

        return ChatAnthropic(**kwargs)

    elif provider == "Ollama":
        from langchain_community.chat_models import ChatOllama

        base_url = model_config.base_url or "http://localhost:11434"
        model_name = model_config.model or "llama3"

        return ChatOllama(
            base_url=base_url,
            model=model_name,
        )

    else:
        raise ValueError(f"Unsupported provider: {provider}")
