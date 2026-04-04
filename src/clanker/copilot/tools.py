"""Copilot tool conversion utilities."""

from __future__ import annotations

from typing import Any, Callable

from clanker.logging import get_logger

logger = get_logger("copilot.tools")

# Callback for tool call notifications (set by streaming layer)
_tool_call_callback: Callable[[str, dict, str | None], None] | None = None


def set_tool_call_callback(callback: Callable[[str, dict, str | None], None] | None) -> None:
    """Register callback for tool call notifications.

    Args:
        callback: Function(tool_name, args, result) called when tools execute.
    """
    global _tool_call_callback
    _tool_call_callback = callback


def get_tool_call_callback() -> Callable[[str, dict, str | None], None] | None:
    """Get the current tool call callback."""
    return _tool_call_callback


def normalize_tool_result(result: Any) -> str:
    """Normalize tool result for display.

    Delegates to centralized function in UI module.
    """
    from clanker.ui.tool_display import normalize_tool_output
    return normalize_tool_output(result)


def convert_langchain_tools_to_copilot(tools: list) -> list:
    """Convert LangChain tools to Copilot tool format.

    Uses define_tool from the Copilot SDK to create properly
    formatted tool definitions with async handlers.

    Args:
        tools: List of LangChain tool objects.

    Returns:
        List of Copilot Tool objects.
    """
    copilot_tools = []

    try:
        from copilot import define_tool
    except ImportError:
        logger.warning("Copilot SDK not available for tool conversion")
        return []

    for tool in tools:
        # Get the Pydantic model for tool parameters if available
        params_type = None
        if hasattr(tool, "args_schema") and tool.args_schema:
            params_type = tool.args_schema

        def make_handler(t):
            """Create an async handler for a LangChain tool."""
            async def handler(params, invocation):
                try:
                    # Convert params (Pydantic model) to dict
                    if params is None:
                        args = {}
                    elif hasattr(params, "model_dump"):
                        args = params.model_dump(exclude_none=True)
                    elif hasattr(params, "dict"):
                        args = params.dict(exclude_none=True)
                    elif isinstance(params, dict):
                        args = params
                    else:
                        args = {}

                    logger.debug("Tool %s called with args: %s", t.name, args)

                    # Always use ainvoke since we're in async context
                    result = await t.ainvoke(args)

                    result_str = str(result)
                    logger.debug("Tool %s result length: %d", t.name, len(result_str))

                    return result_str
                except Exception as e:
                    logger.error("Tool %s error: %s", t.name, e)
                    return f"Error: {str(e)}"
            return handler

        # Create tool using define_tool
        copilot_tool = define_tool(
            name=tool.name,
            description=tool.description or "",
            handler=make_handler(tool),
            params_type=params_type,
            overrides_built_in_tool=True,
        )
        copilot_tools.append(copilot_tool)
        logger.debug("Converted tool: %s", tool.name)

    return copilot_tools
