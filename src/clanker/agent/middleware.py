"""Custom middleware for LangChain agents."""

import json
from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.messages import AIMessage, AnyMessage, ToolMessage

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


def _truncate_text(text: str, max_chars: int, marker: str = _TOOL_TRUNCATION_MARKER) -> str:
    """Head/tail truncate *text* to at most *max_chars*, keeping both ends.

    Tool output is often most useful at the head (what was found) and the tail
    (errors, tracebacks, summaries), so we preserve a slice of each around a
    marker rather than cutting the end off entirely. *marker* defaults to the
    tool-result marker; callers truncating tool-call args pass their own.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    # If the budget is too small to fit the marker, hard-truncate without it so
    # the result never exceeds max_chars.
    if max_chars <= len(marker):
        return text[:max_chars]
    budget = max_chars - len(marker)
    head = (budget * 3) // 5
    tail = budget - head
    if tail <= 0:
        return text[:budget] + marker
    return text[:head] + marker + text[-tail:]


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


# Default per-tool-call-argument budget (tokens) when none is configured.
_DEFAULT_MAX_TOOL_CALL_ARG_TOKENS = 4_000  # ~16 KB per string arg

_TOOL_ARG_TRUNCATION_MARKER = (
    "\n\n... [argument value elided by clanker to keep the request within the "
    "provider's size limit. If this was a file write/edit, the content was "
    "already applied to disk -- re-read the file to see it] ...\n\n"
)


def _truncate_tool_call_args(message: AnyMessage, max_tokens: int) -> AnyMessage:
    """Return a copy of *message* with oversized string tool-call args truncated.

    Only :class:`AIMessage` objects that carry ``tool_calls`` are affected. Every
    *top-level* string argument value longer than the per-arg character budget is
    head/tail truncated with :data:`_TOOL_ARG_TRUNCATION_MARKER`; anything else
    (numbers, bools, already-truncated strings, nested containers) is left as-is.

    Tool names are **not** special-cased -- any large string arg from any tool
    (``write_file``/``append_file`` ``content``, ``edit_file`` ``old_string`` /
    ``new_string``, MCP tools, future tools) is bounded the same way.

    Rewriting ``message.tool_calls`` is sufficient to shrink the wire payload for
    both providers we support: langchain-openai serializes ``tool_calls``
    preferentially over ``additional_kwargs``, and langchain-anthropic prefers the
    ``tool_calls`` entry over the matching ``content`` tool_use block. So we do not
    touch ``content`` blocks or ``additional_kwargs``.

    Returns the SAME object when nothing changed (identity short-circuit, so callers
    can cheaply detect no-ops). Idempotent: the length check and marker guard skip
    already-truncated values.
    """
    if max_tokens <= 0:
        return message
    if not isinstance(message, AIMessage) or not message.tool_calls:
        return message

    max_chars = max_tokens * _CHARS_PER_TOKEN
    changed = False
    new_tool_calls = []
    for tool_call in message.tool_calls:
        args = tool_call.get("args")
        if not isinstance(args, dict):
            new_tool_calls.append(tool_call)
            continue

        new_args = args
        for key, value in args.items():
            if (
                isinstance(value, str)
                and len(value) > max_chars
                and _TOOL_ARG_TRUNCATION_MARKER not in value
            ):
                if new_args is args:
                    new_args = dict(args)  # copy-on-first-write
                new_args[key] = _truncate_text(value, max_chars, _TOOL_ARG_TRUNCATION_MARKER)
                logger.info(
                    "Truncated tool-call arg '%s.%s' from %d chars (~%d token budget)",
                    tool_call.get("name", "?"),
                    key,
                    len(value),
                    max_tokens,
                )

        if new_args is not args:
            changed = True
            new_tool_calls.append({**tool_call, "args": new_args})
        else:
            new_tool_calls.append(tool_call)

    if not changed:
        return message
    return message.model_copy(update={"tool_calls": new_tool_calls})


class ToolCallArgTruncationMiddleware(AgentMiddleware):
    """Bounds oversized tool-call ARGUMENTS on the request path.

    :class:`ToolResultTruncationMiddleware` caps tool *results* (``ToolMessage``).
    It does nothing for the arguments the model sends INTO a tool: ``write_file`` /
    ``append_file`` put the whole file body in ``content``; ``edit_file`` puts whole
    blocks in ``old_string`` / ``new_string``. Those live in the AIMessage's
    ``tool_calls`` and re-send on every subsequent turn, bloating the request until
    a proxy/gateway's HTTP body-byte limit rejects it (``413 Request Entity Too
    Large``) -- which the token-based summarization trigger never catches (413 is a
    byte limit, not a token-context overflow).

    This truncates oversized string args in ``request.messages`` just before the
    model call, WITHOUT mutating persisted checkpoint state (``request.override``
    builds a fresh request; the helper returns copies). The file is already on disk,
    so history needs only a marker. Idempotent and provider-agnostic.

    Place this LAST in the middleware list: first = outermost, last = innermost on
    the request path, so it bounds exactly the messages that hit the wire, after
    summarization has selected its kept window.
    """

    def __init__(self, max_tokens: int = _DEFAULT_MAX_TOOL_CALL_ARG_TOKENS) -> None:
        super().__init__()
        self.tools = []
        self.state_schema = AgentState
        self.max_tokens = max_tokens

    def wrap_model_call(self, request: Any, handler: Callable) -> Any:
        return handler(self._bounded(request))

    async def awrap_model_call(self, request: Any, handler: Callable) -> Any:
        return await handler(self._bounded(request))

    def _bounded(self, request: Any) -> Any:
        """Return *request* with oversized tool-call args truncated, or unchanged.

        Returns the original request object when nothing was oversized, avoiding a
        needless ``override`` allocation on the common path.
        """
        if self.max_tokens <= 0:
            return request
        new_messages = [
            _truncate_tool_call_args(m, self.max_tokens) for m in request.messages
        ]
        if all(new is old for new, old in zip(new_messages, request.messages, strict=True)):
            return request
        return request.override(messages=new_messages)
