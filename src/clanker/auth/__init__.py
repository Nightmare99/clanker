"""Authentication modules for Clanker."""

from clanker.auth.github_copilot import (
    authenticate_github_copilot,
    get_available_copilot_models,
    get_github_token,
    is_github_token_valid,
    GITHUB_TOKEN_PATH,
)

__all__ = [
    "authenticate_github_copilot",
    "get_available_copilot_models",
    "get_github_token",
    "is_github_token_valid",
    "GITHUB_TOKEN_PATH",
]
