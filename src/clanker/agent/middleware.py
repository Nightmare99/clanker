"""Custom middleware for LangChain agents."""

import json
from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.messages import ToolMessage

from clanker.logging import get_logger

logger = get_logger("agent.middleware")


def _process_tool_message(result: Any) -> Any:
    """Helper to convert a ToolMessage containing images into multimodal content."""
    # Check if result is a ToolMessage we can process
    if not isinstance(result, ToolMessage):
        return result

    # Try to parse content as JSON to check for images
    content = result.content
    if not isinstance(content, str):
        return result

    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return result

    if not isinstance(parsed, dict) or "images" not in parsed:
        return result

    images = parsed.get("images", [])
    if not images:
        return result

    # Build multimodal content
    logger.info("Converting tool result to multimodal content with %d images", len(images))

    multimodal_content = []

    # Add text content (without the images array to avoid duplication)
    text_result = {k: v for k, v in parsed.items() if k != "images"}
    text_result["images_included"] = len(images)
    multimodal_content.append({
        "type": "text",
        "text": json.dumps(text_result),
    })

    # Add image content
    for img in images:
        try:
            data = img.get("data", "")
            mime_type = img.get("mime_type", "image/png")
            page = img.get("page", "?")

            # Format as data URL for image_url type
            data_url = f"data:{mime_type};base64,{data}"

            multimodal_content.append({
                "type": "image_url",
                "image_url": {"url": data_url},
            })
            logger.debug("Added image for page %s to multimodal content", page)
        except Exception as e:
            logger.warning("Failed to add image to multimodal content: %s", e)

    # Return new ToolMessage with multimodal content
    return ToolMessage(
        content=multimodal_content,
        tool_call_id=result.tool_call_id,
        name=result.name if hasattr(result, "name") else None,
    )


class MultimodalToolResultsMiddleware(AgentMiddleware):
    """Middleware class that converts tool results with images to multimodal ToolMessages.

    Supports both synchronous and asynchronous agent execution.
    """

    def __init__(self) -> None:
        super().__init__()
        self.tools = []
        self.state_schema = AgentState

    def wrap_tool_call(self, request: Any, handler: Callable) -> Any:
        result = handler(request)
        logger.debug("wrap_tool_call intercepted: %s", type(result).__name__)
        return _process_tool_message(result)

    async def awrap_tool_call(self, request: Any, handler: Callable) -> Any:
        result = await handler(request)
        logger.debug("awrap_tool_call intercepted: %s", type(result).__name__)
        return _process_tool_message(result)


multimodal_tool_results = MultimodalToolResultsMiddleware()


# Approximate characters per token, used only for cheap truncation math.
_CHARS_PER_TOKEN = 4

# Default per-tool-result budget (tokens) when none is configured.
_DEFAULT_MAX_TOOL_RESULT_TOKENS = 20_000

_TOOL_TRUNCATION_MARKER = (
    "\n\n... [tool result truncated by clanker to fit the context window. "
    "Re-run the tool with a narrower scope (e.g. a line range, glob, or grep) "
    "to see the omitted portion] ...\n\n"
)


def _truncate_text(text: str, max_chars: int) -> str:
    """Head/tail truncate *text* to at most *max_chars*, keeping both ends.

    Tool output is often most useful at the head (what was found) and the tail
    (errors, tracebacks, summaries), so we preserve a slice of each around a
    marker rather than cutting the end off entirely.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    # If the budget is too small to fit the marker, hard-truncate without it so
    # the result never exceeds max_chars.
    if max_chars <= len(_TOOL_TRUNCATION_MARKER):
        return text[:max_chars]
    budget = max_chars - len(_TOOL_TRUNCATION_MARKER)
    head = (budget * 3) // 5
    tail = budget - head
    if tail <= 0:
        return text[:budget] + _TOOL_TRUNCATION_MARKER
    return text[:head] + _TOOL_TRUNCATION_MARKER + text[-tail:]


def _truncate_tool_message(result: Any, max_tokens: int) -> Any:
    """Return a copy of *result* with oversized text content truncated.

    Only :class:`ToolMessage` results are affected; anything else (e.g.
    ``Command``) is returned unchanged. For multimodal list content, only text
    blocks are truncated -- ``image_url`` and other non-text blocks are
    preserved intact so this composes safely with
    :class:`MultimodalToolResultsMiddleware`.
    """
    if max_tokens <= 0 or not isinstance(result, ToolMessage):
        return result

    max_chars = max_tokens * _CHARS_PER_TOKEN
    content = result.content

    if isinstance(content, str):
        if len(content) <= max_chars:
            return result
        new_content: Any = _truncate_text(content, max_chars)
        logger.info(
            "Truncated tool result '%s' from %d to %d chars (~%d token budget)",
            result.name or "?",
            len(content),
            len(new_content),
            max_tokens,
        )
        return _copy_tool_message(result, new_content)

    if isinstance(content, list):
        # Budget applies to the textual portion; images are left untouched.
        text_len = sum(
            len(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
        text_len += sum(len(block) for block in content if isinstance(block, str))
        if text_len <= max_chars:
            return result

        new_blocks: list[Any] = []
        for block in content:
            if isinstance(block, str):
                new_blocks.append(_truncate_text(block, max_chars))
            elif isinstance(block, dict) and block.get("type") == "text":
                new_blocks.append(
                    {**block, "text": _truncate_text(block.get("text", ""), max_chars)}
                )
            else:
                new_blocks.append(block)
        logger.info(
            "Truncated multimodal tool result '%s' text from %d chars (~%d token budget)",
            result.name or "?",
            text_len,
            max_tokens,
        )
        return _copy_tool_message(result, new_blocks)

    return result


def _copy_tool_message(result: ToolMessage, new_content: Any) -> ToolMessage:
    """Copy *result* with replaced content, preserving all other fields."""
    try:
        return result.model_copy(update={"content": new_content})
    except Exception:  # noqa: BLE001 - never let copying break the tool loop
        return ToolMessage(
            content=new_content,
            tool_call_id=result.tool_call_id,
            name=result.name if hasattr(result, "name") else None,
        )


class ToolResultTruncationMiddleware(AgentMiddleware):
    """Caps the size of any single tool result before it enters the conversation.

    Summarization only bounds the *model input* it can see, and it preserves the
    most recent messages verbatim. A single oversized tool result (a large
    ``read_file``, a verbose MCP tool, etc.) can therefore sit in the preserved
    window and overflow the context window on the very next model call. This
    middleware closes that gap by head/tail-truncating oversized
    :class:`ToolMessage` content at the tool boundary -- the one place every tool
    result (built-in and MCP) is guaranteed to pass through.

    Place this FIRST in the middleware list so that, on the response path, it
    runs *after* :class:`MultimodalToolResultsMiddleware` has extracted images
    into structured blocks (image blocks are then preserved, only text is cut).
    """

    def __init__(self, max_tokens: int = _DEFAULT_MAX_TOOL_RESULT_TOKENS) -> None:
        super().__init__()
        self.tools = []
        self.state_schema = AgentState
        self.max_tokens = max_tokens

    def wrap_tool_call(self, request: Any, handler: Callable) -> Any:
        result = handler(request)
        return _truncate_tool_message(result, self.max_tokens)

    async def awrap_tool_call(self, request: Any, handler: Callable) -> Any:
        result = await handler(request)
        return _truncate_tool_message(result, self.max_tokens)
