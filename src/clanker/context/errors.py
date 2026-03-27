"""Utilities for detecting context-length errors from LLM providers."""

from __future__ import annotations


# Keywords found in error messages from every provider we support.
_CONTEXT_LENGTH_PHRASES = (
    "prompt is too long",
    "maximum context length",
    "context_length_exceeded",
    "context window",
    "too many tokens",
    "string_above_max_length",
    "input is too long",
    "reduce the length",
    "exceeds the model",
    "tokens in the input",
    "request too large",
)

# HTTP status codes that indicate a payload-too-large / bad-request
# caused by context overflow.  413 is "Request Entity Too Large";
# 400 is used by both OpenAI and Anthropic for context errors.
_CONTEXT_LENGTH_STATUS_CODES = (400, 413)


def is_context_length_error(exc: BaseException) -> bool:
    """Return True if *exc* is a context-length / token-limit error.

    Works across all supported providers (OpenAI, Azure OpenAI, Anthropic,
    Azure Anthropic) without importing provider-specific packages at the
    module level (they may not be installed).

    Detection strategy (in order):
    1. Check ``status_code`` attribute (openai / anthropic SDK errors).
    2. Check ``code`` attribute set by openai SDK for structured errors.
    3. Scan the string representation for well-known phrases.
    """
    # 1. Status-code based detection ----------------------------------------
    status_code: int | None = getattr(exc, "status_code", None)
    if status_code in _CONTEXT_LENGTH_STATUS_CODES:
        # Not every 400/413 is a context error – confirm via message/code.
        code: str | None = getattr(exc, "code", None)
        if code and _matches_phrase(code):
            return True
        if _matches_phrase(str(exc)):
            return True
        # 413 is almost always "request too large" – treat as context error.
        if status_code == 413:
            return True

    # 2. Structured error code (OpenAI) -------------------------------------
    code = getattr(exc, "code", None)
    if code and _matches_phrase(code):
        return True

    # 3. Message scan --------------------------------------------------------
    return _matches_phrase(str(exc))


def _matches_phrase(text: str) -> bool:
    """Return True if *text* contains any known context-length indicator."""
    lower = text.lower()
    return any(phrase in lower for phrase in _CONTEXT_LENGTH_PHRASES)
