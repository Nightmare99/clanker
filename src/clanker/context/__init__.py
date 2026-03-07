"""Context management for Clanker."""

from clanker.context.compaction import (
    compact_context_sync,
    should_compact,
)

__all__ = [
    "compact_context_sync",
    "should_compact",
]
