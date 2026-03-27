"""Context management for Clanker."""

from clanker.context.compaction import (
    compact_context_sync,
    should_compact,
)
from clanker.context.errors import is_context_length_error

__all__ = [
    "compact_context_sync",
    "should_compact",
    "is_context_length_error",
]
