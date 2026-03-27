"""Context compaction utilities.

The actual summarization is handled by LangChain's SummarizationMiddleware
in the agent graph. This module provides utility functions for context management.
"""

from clanker.config import get_settings
from clanker.logging import get_logger

logger = get_logger("compaction")


def should_compact(context_used_percent: float, threshold: float | None = None) -> bool:
    """Check if context compaction is needed.

    Note: With SummarizationMiddleware, compaction happens automatically.
    This function is kept for token tracking display purposes.

    Args:
        context_used_percent: Current percentage of context window used.
        threshold: Percentage threshold to trigger compaction (uses settings if None).

    Returns:
        True if compaction should be performed.
    """
    if threshold is None:
        threshold = get_settings().context.compaction_threshold
    return context_used_percent >= threshold
