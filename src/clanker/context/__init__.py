"""Context management for Clanker."""

from clanker.context.compaction import should_compact
from clanker.context.errors import is_context_length_error

__all__ = [
    "should_compact",
    "is_context_length_error",
]
