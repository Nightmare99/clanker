"""Context compaction to handle long conversations."""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from clanker.config import get_settings
from clanker.logging import get_logger

logger = get_logger("compaction")


SUMMARY_PROMPT = """You are a conversation summarizer. Summarize the following conversation history concisely, preserving:
1. Key decisions made
2. Important code changes or file modifications
3. User preferences discovered
4. Current task context and progress

Be concise but complete. Focus on information needed to continue the conversation effectively.

CONVERSATION TO SUMMARIZE:
{conversation}

SUMMARY:"""


def should_compact(context_used_percent: float, threshold: float | None = None) -> bool:
    """Check if context compaction is needed.

    Args:
        context_used_percent: Current percentage of context window used.
        threshold: Percentage threshold to trigger compaction (uses settings if None).

    Returns:
        True if compaction should be performed.
    """
    if threshold is None:
        threshold = get_settings().context.compaction_threshold
    return context_used_percent >= threshold


def format_messages_for_summary(messages: list) -> str:
    """Format messages into a string for summarization.

    Args:
        messages: List of LangChain messages.

    Returns:
        Formatted conversation string.
    """
    lines = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            continue  # Skip system messages
        elif isinstance(msg, HumanMessage):
            role = "Human"
        elif isinstance(msg, AIMessage):
            role = "Assistant"
        else:
            role = "Unknown"

        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        # Truncate very long messages
        if len(content) > 1000:
            content = content[:1000] + "... [truncated]"
        lines.append(f"{role}: {content}")

    return "\n\n".join(lines)


def get_messages_to_compact(messages: list, keep_recent: int | None = None) -> tuple[list, list]:
    """Split messages into those to compact and those to keep.

    Args:
        messages: Full message list.
        keep_recent: Number of recent turns to keep (uses settings if None).

    Returns:
        Tuple of (messages_to_compact, messages_to_keep).
    """
    if keep_recent is None:
        keep_recent = get_settings().context.keep_recent_turns

    # Filter out system messages for counting
    non_system = [m for m in messages if not isinstance(m, SystemMessage)]

    # Count turns (each turn = 1 human + 1 AI message)
    # We want to keep the last `keep_recent` turns
    messages_to_keep_count = keep_recent * 2  # human + AI pairs

    if len(non_system) <= messages_to_keep_count:
        # Not enough messages to compact
        return [], messages

    # Split at the boundary
    split_point = len(non_system) - messages_to_keep_count
    to_compact = non_system[:split_point]
    to_keep = non_system[split_point:]

    return to_compact, to_keep


async def compact_context_async(
    messages: list,
    model,
    context_used_percent: float,
    console=None,
) -> tuple[list, bool]:
    """Compact conversation context by summarizing older messages.

    Args:
        messages: Full conversation history.
        model: LLM model to use for summarization.
        context_used_percent: Current context usage percentage.
        console: Optional console for status output.

    Returns:
        Tuple of (compacted_messages, was_compacted).
    """
    if not should_compact(context_used_percent):
        return messages, False

    to_compact, to_keep = get_messages_to_compact(messages)

    if not to_compact:
        logger.debug("No messages to compact")
        return messages, False

    logger.info(
        "Compacting context: %d messages to summarize, keeping %d recent",
        len(to_compact), len(to_keep)
    )

    if console:
        console.print_info(f"Compacting context ({context_used_percent:.0f}% used)...")

    # Format messages for summarization
    conversation_text = format_messages_for_summary(to_compact)

    # Generate summary
    try:
        summary_prompt = SUMMARY_PROMPT.format(conversation=conversation_text)
        response = await model.ainvoke([HumanMessage(content=summary_prompt)])
        summary = response.content if isinstance(response.content, str) else str(response.content)

        logger.info("Context compacted: %d chars summarized to %d chars",
                   len(conversation_text), len(summary))

        if console:
            console.print_info(f"Compacted {len(to_compact)} messages into summary")

        # Create new message list with summary
        summary_message = SystemMessage(
            content=f"[CONVERSATION SUMMARY - Earlier messages have been compacted]\n{summary}\n[END SUMMARY]"
        )

        # Return: summary + recent messages
        compacted = [summary_message] + to_keep
        return compacted, True

    except Exception as e:
        logger.error("Failed to compact context: %s", e)
        if console:
            console.print_warning(f"Context compaction failed: {e}")
        return messages, False


def compact_context_sync(
    messages: list,
    model,
    context_used_percent: float,
    console=None,
) -> tuple[list, bool]:
    """Synchronous wrapper for context compaction.

    Args:
        messages: Full conversation history.
        model: LLM model to use for summarization.
        context_used_percent: Current context usage percentage.
        console: Optional console for status output.

    Returns:
        Tuple of (compacted_messages, was_compacted).
    """
    import asyncio

    return asyncio.run(compact_context_async(
        messages, model, context_used_percent, console
    ))
