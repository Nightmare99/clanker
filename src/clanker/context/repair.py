"""Repair utilities for conversation message history.

When an agent turn is interrupted (Ctrl+C) after the model has emitted an
``AIMessage`` containing ``tool_calls`` but before the tool node has run and
written the matching ``ToolMessage`` results, the persisted graph state is left
holding *orphaned* ``tool_use`` blocks. Anthropic-family APIs reject any request
where a ``tool_use`` id has no corresponding ``tool_result`` in the next
message, so every subsequent turn on that thread fails with a 400 until the
state is healed.

These helpers detect orphaned tool calls and synthesize stub ``ToolMessage``
results so the history is valid again. Synthesizing stubs (rather than dropping
the ``AIMessage``) preserves the model's own reasoning text and the fact that it
*intended* to call those tools, which is better context than silently erasing
the turn.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage

INTERRUPTED_TOOL_RESULT = "[Tool execution was interrupted before completion.]"


def find_orphaned_tool_call_ids(messages: list[AnyMessage]) -> list[str]:
    """Return tool_call ids that have no corresponding ToolMessage result.

    A tool_call is orphaned when an ``AIMessage`` requests it but no later
    ``ToolMessage`` carries a matching ``tool_call_id``.

    Args:
        messages: The conversation history to inspect.

    Returns:
        Ordered list of orphaned tool_call ids (de-duplicated, first-seen order).
    """
    satisfied = {
        m.tool_call_id
        for m in messages
        if isinstance(m, ToolMessage) and m.tool_call_id
    }

    orphans: list[str] = []
    seen: set[str] = set()
    for m in messages:
        if not isinstance(m, AIMessage):
            continue
        for tc in getattr(m, "tool_calls", None) or []:
            tc_id = tc.get("id")
            if tc_id and tc_id not in satisfied and tc_id not in seen:
                orphans.append(tc_id)
                seen.add(tc_id)
    return orphans


def make_tool_result_stubs(orphan_ids: list[str]) -> list[ToolMessage]:
    """Build stub ToolMessage results for the given orphaned tool_call ids.

    Args:
        orphan_ids: tool_call ids needing a synthetic result.

    Returns:
        One ToolMessage per id, in the same order.
    """
    return [
        ToolMessage(content=INTERRUPTED_TOOL_RESULT, tool_call_id=tc_id)
        for tc_id in orphan_ids
    ]
