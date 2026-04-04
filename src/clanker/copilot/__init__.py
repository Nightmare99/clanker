"""GitHub Copilot mode - session management and SDK integration."""

# Auth
from clanker.copilot.auth import (
    authenticate_copilot_sync,
    get_github_token,
    load_copilot_token,
    save_copilot_token,
)

# Client
from clanker.copilot.client import (
    cleanup as cleanup_client,
    ensure_client,
    get_client,
    get_model_token_limit,
    get_model_token_limit_sync,
    is_available,
    list_models,
)

# Session
from clanker.copilot.session import (
    CopilotSessionManager,
    get_copilot_session_manager,
    reset_copilot_session_manager,
)

# Tools
from clanker.copilot.tools import (
    convert_langchain_tools_to_copilot,
    get_tool_call_callback,
    normalize_tool_result,
    set_tool_call_callback,
)

# Registry
from clanker.copilot.registry import (
    load_session_registry,
    register_session,
    unregister_session,
)

__all__ = [
    # Auth
    "authenticate_copilot_sync",
    "get_github_token",
    "load_copilot_token",
    "save_copilot_token",
    # Client
    "cleanup_client",
    "ensure_client",
    "get_client",
    "get_model_token_limit",
    "get_model_token_limit_sync",
    "is_available",
    "list_models",
    # Session
    "CopilotSessionManager",
    "get_copilot_session_manager",
    "reset_copilot_session_manager",
    # Tools
    "convert_langchain_tools_to_copilot",
    "get_tool_call_callback",
    "normalize_tool_result",
    "set_tool_call_callback",
    # Registry
    "load_session_registry",
    "register_session",
    "unregister_session",
]
