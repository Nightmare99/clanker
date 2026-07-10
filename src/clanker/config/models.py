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

# Default seconds to wait for the next streamed chunk before erroring. Higher
# than langchain_openai's stock 120s so high-reasoning models (which can pause
# silently for minutes mid-stream) don't trip a false "connection dead" timeout,
# while still catching genuinely stalled TCP connections.
DEFAULT_STREAM_CHUNK_TIMEOUT = 600

ProviderType = Literal["AzureOpenAI", "OpenAI", "Anthropic", "Ollama", "GitHubCopilot"]


def _resolve_stream_chunk_timeout(model_config: "ModelConfig") -> int | None:
    """Resolve the stream-chunk timeout for an OpenAI/Azure model.

    Returns the per-model override when set, clanker's default when unset, and
    ``None`` (disabled) when explicitly set to 0.
    """
    configured = model_config.stream_chunk_timeout
    if configured is None:
        return DEFAULT_STREAM_CHUNK_TIMEOUT
    if configured <= 0:
        return None
    return configured


def _apply_stream_chunk_timeout(chat_cls, kwargs: dict, model_config: "ModelConfig") -> None:
    """Apply the stream-chunk timeout in a version-safe way.

    The stream-chunk-timeout feature only exists in newer ``langchain-openai``
    releases. On versions that expose ``stream_chunk_timeout`` as a real model
    field we pass it as a constructor kwarg. On older versions it is NOT a field
    -- passing it would silently fall into ``model_kwargs`` and then be forwarded
    to the API call, which rejects it ("unexpected keyword argument") and breaks
    every request. For those, we set the ``LANGCHAIN_OPENAI_STREAM_CHUNK_TIMEOUT_S``
    env var instead, which newer versions read and older ones harmlessly ignore.

    A value of ``None`` (disabled) is applied as ``0`` to the env var path.
    """
    timeout = _resolve_stream_chunk_timeout(model_config)

    supports_field = "stream_chunk_timeout" in getattr(chat_cls, "model_fields", {})
    if supports_field:
        kwargs["stream_chunk_timeout"] = timeout
        return

    # Older version: never let it reach model_kwargs. Use the documented env var.
    os.environ["LANGCHAIN_OPENAI_STREAM_CHUNK_TIMEOUT_S"] = str(timeout if timeout else 0)


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
    max_input_tokens: int | None = Field(default=None, description="Maximum input tokens (for OpenRouter/custom endpoints)")

    # Extended thinking (Anthropic)
    thinking_enabled: bool = Field(default=False, description="Enable extended thinking mode")
    thinking_budget_tokens: int = Field(default=10000, description="Token budget for thinking")

    # Reasoning effort (Azure OpenAI o1/o3 models)
    reasoning_effort: str | None = Field(default=None, description="Reasoning effort: low, medium, high")

    # Streaming reliability: max seconds to wait for the next streamed chunk
    # before erroring. langchain_openai defaults to 120s, which is too low for
    # high-reasoning models that pause silently while thinking. None uses
    # clanker's default; 0 disables the timeout entirely. (OpenAI/Azure only.)
    stream_chunk_timeout: int | None = Field(
        default=None,
        description="Seconds to wait for the next stream chunk (None=default, 0=disabled)",
    )

    # Cost tracking (USD per million tokens). All fields are optional; when
    # none are set, the cost display is skipped. Prices follow the standard
    # "per-million-tokens" unit used by every major provider's pricing page.
    cost_input: float | None = Field(
        default=None,
        description="Input token cost in USD per million tokens",
    )
    cost_output: float | None = Field(
        default=None,
        description="Output token cost in USD per million tokens",
    )
    cost_cache_read: float | None = Field(
        default=None,
        description="Cache-read token cost in USD per million tokens (Anthropic prompt caching)",
    )
    cost_cache_creation: float | None = Field(
        default=None,
        description="Cache-creation token cost in USD per million tokens (Anthropic prompt caching)",
    )

    def compute_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> float | None:
        """Compute the USD cost for a single LLM call.

        Returns None when no cost fields are configured so the caller can
        distinguish "no cost data" from "zero cost".

        Pricing formula: (tokens / 1_000_000) * price_per_million.
        Cache-read tokens replace regular input tokens at a discounted rate
        for Anthropic models; we bill them separately here.
        """
        if (
            self.cost_input is None
            and self.cost_output is None
            and self.cost_cache_read is None
            and self.cost_cache_creation is None
        ):
            return None

        cost = 0.0
        if self.cost_input is not None:
            cost += (input_tokens / 1_000_000) * self.cost_input
        if self.cost_output is not None:
            cost += (output_tokens / 1_000_000) * self.cost_output
        if self.cost_cache_read is not None:
            cost += (cache_read_tokens / 1_000_000) * self.cost_cache_read
        if self.cost_cache_creation is not None:
            cost += (cache_creation_tokens / 1_000_000) * self.cost_cache_creation
        return cost

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
        json.dump(config.model_dump(exclude_none=True), f, indent=2)

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

        # Model profile for OpenRouter/custom endpoints (needed for fractional token limits)
        if model_config.max_input_tokens:
            kwargs["profile"] = {"max_input_tokens": model_config.max_input_tokens}

        # Tolerate long silent reasoning pauses without tripping the stream timeout
        # (version-safe: kwarg on newer langchain-openai, env var on older).
        _apply_stream_chunk_timeout(ChatOpenAI, kwargs, model_config)

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

        # Model profile (needed for fractional token limits, e.g. summarization)
        if model_config.max_input_tokens:
            kwargs["profile"] = {"max_input_tokens": model_config.max_input_tokens}

        # Tolerate long silent reasoning pauses without tripping the stream timeout
        # (version-safe: kwarg on newer langchain-openai, env var on older).
        _apply_stream_chunk_timeout(AzureChatOpenAI, kwargs, model_config)

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

        # Model profile (needed for fractional token limits, e.g. summarization)
        if model_config.max_input_tokens:
            kwargs["profile"] = {"max_input_tokens": model_config.max_input_tokens}

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

    elif provider == "GitHubCopilot":
        from langchain_openai import ChatOpenAI

        from clanker.config.copilot_auth import (
            COPILOT_BASE_URL,
            copilot_request_headers,
            get_valid_copilot_token,
        )

        # Eager check: raises CopilotAuthError with a clear message right now if
        # never logged in, instead of surfacing as an opaque SDK auth failure on
        # the first real request. The RESOLVED token is discarded -- see below.
        get_valid_copilot_token()

        kwargs = {
            "base_url": COPILOT_BASE_URL,
            "default_headers": copilot_request_headers(),
        }
        if model_config.model:
            kwargs["model"] = model_config.model

        if model_config.max_tokens:
            kwargs["max_tokens"] = model_config.max_tokens

        # Model profile (needed for fractional token limits, e.g. summarization)
        if model_config.max_input_tokens:
            kwargs["profile"] = {"max_input_tokens": model_config.max_input_tokens}

        # Tolerate long silent reasoning pauses without tripping the stream timeout
        # (version-safe: kwarg on newer langchain-openai, env var on older).
        _apply_stream_chunk_timeout(ChatOpenAI, kwargs, model_config)

        # Pass the FUNCTION itself as api_key, not a resolved token string.
        # ChatOpenAI's underlying openai.OpenAI/AsyncOpenAI clients call this
        # provider fresh before every request (openai's own
        # BaseClient._prepare_options -> _refresh_api_key), so a token that
        # expires mid-turn (a turn can span many tool-calling round-trips,
        # hence many model calls) is refreshed on the very next call instead
        # of every subsequent call in that turn reusing a now-stale token
        # that would otherwise be frozen in at construction time.
        return ChatOpenAI(
            api_key=get_valid_copilot_token,
            stream_usage=True,
            **kwargs,
        )

    else:
        raise ValueError(f"Unsupported provider: {provider}")
