"""Custom LLM providers for Clanker."""

from clanker.providers.github_copilot import (
    ChatGitHubCopilot,
    get_copilot_client,
    list_copilot_models,
    is_copilot_available,
    cleanup_copilot,
    authenticate_copilot_sync,
    _load_copilot_token,
    set_tool_call_callback,
    get_tool_call_callback,
)

__all__ = [
    "ChatGitHubCopilot",
    "get_copilot_client",
    "list_copilot_models",
    "is_copilot_available",
    "cleanup_copilot",
    "authenticate_copilot_sync",
    "_load_copilot_token",
    "set_tool_call_callback",
    "get_tool_call_callback",
]
