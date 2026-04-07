"""Copilot SDK client management."""

from __future__ import annotations

import asyncio
from typing import Any

from clanker.logging import get_logger

logger = get_logger("copilot.client")

# Global client state
_copilot_client: Any = None
_copilot_loop_id: int | None = None
_copilot_models_cache: dict[str, int] | None = None


async def ensure_client() -> Any:
    """Ensure the Copilot client is initialized.

    Creates a new client if none exists, or if the event loop has changed.
    Handles token acquisition automatically.

    Returns:
        The initialized CopilotClient instance.

    Raises:
        ImportError: If github-copilot-sdk is not installed.
        RuntimeError: If authentication fails.
    """
    global _copilot_client, _copilot_loop_id

    # Check if we need to recreate the client (event loop changed)
    current_loop_id = id(asyncio.get_event_loop())
    if _copilot_client is not None and _copilot_loop_id != current_loop_id:
        logger.debug("Event loop changed, resetting Copilot client")
        _copilot_client = None

    if _copilot_client is None:
        try:
            from copilot import CopilotClient
            from copilot.types import SubprocessConfig
        except ImportError:
            raise ImportError(
                "github-copilot-sdk is not installed. "
                "Install it with: pip install github-copilot-sdk"
            )

        # Try to get Copilot token
        from clanker.copilot.auth import get_github_token, load_copilot_token, authenticate_copilot_sync

        token = get_github_token() or load_copilot_token()

        if not token:
            # Need to authenticate
            logger.info("No Copilot token found, starting device flow authentication")
            token = authenticate_copilot_sync()

        # Pass token directly via SubprocessConfig
        config = SubprocessConfig(
            github_token=token,
            use_logged_in_user=False,
        )
        _copilot_client = CopilotClient(config)
        _copilot_loop_id = current_loop_id
        logger.info("GitHub Copilot client initialized with explicit token")

        await _copilot_client.start()

        # Populate models cache
        await _populate_models_cache()

    return _copilot_client


async def _populate_models_cache() -> None:
    """Fetch and cache model information from SDK."""
    global _copilot_models_cache

    if _copilot_client is None:
        return

    try:
        models = await _copilot_client.list_models()
        _copilot_models_cache = {}
        for m in models:
            limits = getattr(m.capabilities, 'limits', None)
            max_tokens = getattr(limits, 'max_context_window_tokens', 128000) if limits else 128000
            _copilot_models_cache[m.id] = max_tokens
        logger.debug("Cached %d Copilot models", len(_copilot_models_cache))
    except Exception as e:
        logger.warning("Failed to cache model info: %s", e)


async def get_model_token_limit(model_id: str) -> int:
    """Get max token limit for a model from SDK, with caching.

    Args:
        model_id: The model identifier.

    Returns:
        Maximum context window tokens for the model.
    """
    global _copilot_models_cache

    # Return from cache if available
    if _copilot_models_cache and model_id in _copilot_models_cache:
        return _copilot_models_cache[model_id]

    # Fetch models and build cache
    try:
        client = await ensure_client()
        models = await client.list_models()
        _copilot_models_cache = {}
        for m in models:
            limits = getattr(m.capabilities, 'limits', None)
            max_tokens = getattr(limits, 'max_context_window_tokens', 128000) if limits else 128000
            _copilot_models_cache[m.id] = max_tokens

        return _copilot_models_cache.get(model_id, 128000)
    except Exception as e:
        logger.warning("Failed to fetch model limits: %s", e)
        return 128000  # Default fallback


def get_model_token_limit_sync(model_id: str) -> int:
    """Synchronous wrapper to get model token limit.

    Returns cached value or default if not available.
    """
    global _copilot_models_cache

    if _copilot_models_cache and model_id in _copilot_models_cache:
        return _copilot_models_cache[model_id]

    return 128000  # Default


async def list_models() -> list[dict]:
    """List available Copilot models from subscription.

    Returns:
        List of model info dicts with 'id', 'name', and 'capabilities'.
    """
    try:
        client = await ensure_client()
        models = await client.list_models()
        return [
            {
                "id": m.id,
                "name": m.name,
                "capabilities": {
                    "vision": getattr(m.capabilities.supports, "vision", False),
                    "reasoning": getattr(m.capabilities.supports, "reasoning_effort", False),
                    "max_tokens": getattr(m.capabilities.limits, "max_context_window_tokens", None),
                }
            }
            for m in models
        ]
    except Exception as e:
        logger.warning("Failed to list Copilot models: %s", e)
        return []


def get_client() -> Any:
    """Get the global Copilot client instance (may be None)."""
    return _copilot_client


def is_available() -> bool:
    """Check if GitHub Copilot SDK is available."""
    try:
        from copilot import CopilotClient
        return True
    except ImportError:
        return False


async def cleanup() -> None:
    """Clean up Copilot client."""
    global _copilot_client, _copilot_loop_id, _copilot_models_cache

    if _copilot_client is not None:
        try:
            await _copilot_client.stop()
        except Exception as e:
            logger.warning("Error stopping client: %s", e)
        _copilot_client = None

    _copilot_loop_id = None
    _copilot_models_cache = None
    logger.info("GitHub Copilot client cleaned up")
