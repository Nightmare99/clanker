"""Simple markdown-based memories system for Clanker.

Stores memories as markdown files with YAML frontmatter for tags.
Memories persist across conversations and are retrieved based on tags and keywords.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from clanker.memory.workspace import get_workspace_storage


class MemorySource(str, Enum):
    """Source of a memory."""

    USER = "user"  # User explicitly asked to remember
    AUTO = "auto"  # Agent auto-generated
    SYSTEM = "system"  # System-generated


@dataclass
class Memory:
    """A single memory entry."""

    content: str
    source: MemorySource = MemorySource.USER
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_markdown(self) -> str:
        """Convert to markdown with YAML frontmatter."""
        lines = ["---"]
        lines.append(f"id: {self.id}")
        lines.append(f"source: {self.source.value}")
        lines.append(f"created: {self.created_at}")
        if self.tags:
            lines.append(f"tags: [{', '.join(self.tags)}]")
        lines.append("---")
        lines.append("")
        lines.append(self.content)
        return "\n".join(lines)

    @classmethod
    def from_markdown(cls, content: str, file_id: str | None = None) -> "Memory":
        """Parse a Memory from markdown with YAML frontmatter."""
        # Extract frontmatter
        frontmatter = {}
        body = content

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                frontmatter_text = parts[1].strip()
                body = parts[2].strip()

                # Simple YAML parsing
                for line in frontmatter_text.split("\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        key = key.strip()
                        value = value.strip()

                        # Parse tags list
                        if key == "tags" and value.startswith("["):
                            value = [t.strip() for t in value[1:-1].split(",") if t.strip()]
                        frontmatter[key] = value

        return cls(
            id=frontmatter.get("id", file_id or str(uuid.uuid4())[:8]),
            content=body,
            source=MemorySource(frontmatter.get("source", "user")),
            tags=frontmatter.get("tags", []) if isinstance(frontmatter.get("tags"), list) else [],
            created_at=frontmatter.get("created", datetime.now().isoformat()),
            metadata={},
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "content": self.content,
            "source": self.source.value,
            "tags": self.tags,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Memory":
        """Create a Memory from a dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            content=data["content"],
            source=MemorySource(data.get("source", "user")),
            tags=data.get("tags", []),
            created_at=data.get("created_at", datetime.now().isoformat()),
            metadata=data.get("metadata", {}),
        )


class MemoryStore:
    """Markdown-based memory store."""

    def __init__(self, workspace_path: str | Path | None = None):
        """Initialize the memory store.

        Args:
            workspace_path: Optional workspace path. Defaults to current directory.
        """
        self._storage = get_workspace_storage(workspace_path)
        self._memories_dir: Path | None = None

    def _get_memories_dir(self) -> Path:
        """Get the memories directory path."""
        if self._memories_dir is None:
            self._memories_dir = self._storage.clanker_dir / "memories"
            self._memories_dir.mkdir(parents=True, exist_ok=True)
        return self._memories_dir

    def _get_memory_path(self, memory_id: str) -> Path:
        """Get the path for a specific memory file."""
        return self._get_memories_dir() / f"{memory_id}.md"

    def _load_memory(self, path: Path) -> Memory | None:
        """Load a memory from a file."""
        try:
            content = path.read_text(encoding="utf-8")
            file_id = path.stem
            return Memory.from_markdown(content, file_id)
        except Exception:
            return None

    def add(
        self,
        content: str,
        source: MemorySource = MemorySource.USER,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Memory:
        """Add a new memory.

        Args:
            content: The memory content (markdown supported).
            source: Source of the memory.
            tags: Tags for categorization and retrieval.
            metadata: Optional additional metadata.

        Returns:
            The created Memory.
        """
        memory = Memory(
            content=content,
            source=source,
            tags=tags or [],
            metadata=metadata or {},
        )

        # Save to file
        path = self._get_memory_path(memory.id)
        path.write_text(memory.to_markdown(), encoding="utf-8")

        return memory

    def get(self, memory_id: str) -> Memory | None:
        """Get a specific memory by ID.

        Args:
            memory_id: The memory ID.

        Returns:
            The Memory or None if not found.
        """
        path = self._get_memory_path(memory_id)
        if path.exists():
            return self._load_memory(path)
        return None

    def list_all(self, limit: int = 100) -> list[Memory]:
        """List all memories.

        Args:
            limit: Maximum number of memories to return.

        Returns:
            List of all memories, newest first.
        """
        memories = []
        memories_dir = self._get_memories_dir()

        for path in memories_dir.glob("*.md"):
            memory = self._load_memory(path)
            if memory:
                memories.append(memory)

        # Sort by created_at descending
        memories.sort(key=lambda m: m.created_at, reverse=True)
        return memories[:limit]

    def search(
        self,
        query: str | None = None,
        tags: list[str] | None = None,
        n_results: int = 10,
    ) -> list[Memory]:
        """Search memories by tags and/or keywords.

        Args:
            query: Optional text query for keyword matching.
            tags: Optional tags to filter by (matches any).
            n_results: Maximum number of results.

        Returns:
            List of matching memories.
        """
        all_memories = self.list_all(limit=1000)
        results = []

        query_lower = query.lower() if query else None
        query_words = set(query_lower.split()) if query_lower else set()

        for memory in all_memories:
            score = 0

            # Tag matching (high priority)
            if tags:
                matching_tags = set(memory.tags) & set(tags)
                if matching_tags:
                    score += len(matching_tags) * 10
                else:
                    continue  # Skip if tags specified but none match

            # Keyword matching
            if query_lower:
                content_lower = memory.content.lower()
                content_words = set(content_lower.split())

                # Word overlap
                word_matches = len(query_words & content_words)
                score += word_matches * 2

                # Substring match bonus
                if query_lower in content_lower:
                    score += 5

                # Tag keyword match
                for tag in memory.tags:
                    if query_lower in tag.lower():
                        score += 3

            if score > 0 or (not tags and not query):
                results.append((score, memory))

        # Sort by score descending
        results.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in results[:n_results]]

    def get_by_tags(self, tags: list[str], n_results: int = 10) -> list[Memory]:
        """Get memories that match any of the given tags.

        Args:
            tags: Tags to match.
            n_results: Maximum number of results.

        Returns:
            List of matching memories.
        """
        return self.search(tags=tags, n_results=n_results)

    def delete(self, memory_id: str) -> bool:
        """Delete a memory by ID.

        Args:
            memory_id: The memory ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        path = self._get_memory_path(memory_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def clear(self) -> None:
        """Clear all memories."""
        memories_dir = self._get_memories_dir()
        for path in memories_dir.glob("*.md"):
            path.unlink()

    def count(self) -> int:
        """Get the number of memories."""
        return len(list(self._get_memories_dir().glob("*.md")))

    def get_all_tags(self) -> list[str]:
        """Get all unique tags across all memories.

        Returns:
            Sorted list of unique tags.
        """
        tags = set()
        for memory in self.list_all(limit=1000):
            tags.update(memory.tags)
        return sorted(tags)

    def get_memories_summary(self) -> str:
        """Get a summary of available memories and their tags.

        Returns:
            Formatted summary string for the agent.
        """
        memories = self.list_all(limit=100)
        if not memories:
            return ""

        # Group by tags
        tag_memories: dict[str, list[Memory]] = {}
        untagged: list[Memory] = []

        for memory in memories:
            if memory.tags:
                for tag in memory.tags:
                    if tag not in tag_memories:
                        tag_memories[tag] = []
                    tag_memories[tag].append(memory)
            else:
                untagged.append(memory)

        lines = ["## Available Memories", ""]
        lines.append(f"Total: {len(memories)} memories")
        lines.append("")

        if tag_memories:
            lines.append("### By Tag:")
            for tag in sorted(tag_memories.keys()):
                count = len(tag_memories[tag])
                lines.append(f"- `{tag}`: {count} memories")

        if untagged:
            lines.append(f"- (untagged): {len(untagged)} memories")

        lines.append("")
        lines.append("Use tags to retrieve relevant memories.")

        return "\n".join(lines)

    def get_relevant_context(self, query: str, tags: list[str] | None = None, max_memories: int = 5) -> str:
        """Get relevant memories formatted for injection into context.

        Args:
            query: The current conversation context/query.
            tags: Optional tags to prioritize.
            max_memories: Maximum number of memories to include.

        Returns:
            Formatted string of relevant memories for the system prompt.
        """
        if self.count() == 0:
            return ""

        # Search with query and optional tags
        memories = self.search(query=query, tags=tags, n_results=max_memories)

        if not memories:
            return ""

        lines = ["## Relevant Workspace Memories", ""]
        lines.append("The following remembered information may be relevant:")
        lines.append("")

        for memory in memories:
            tags_str = f" [tags: {', '.join(memory.tags)}]" if memory.tags else ""
            content_lines = memory.content.strip().split("\n")
            if len(content_lines) == 1:
                lines.append(f"- {memory.content}{tags_str}")
            else:
                lines.append(f"- **Memory ({memory.id})**:{tags_str}")
                for line in content_lines[:5]:  # Limit preview
                    lines.append(f"  {line}")
                if len(content_lines) > 5:
                    lines.append(f"  ... ({len(content_lines) - 5} more lines)")

        return "\n".join(lines)


# Backwards compatibility
VectorMemoryStore = MemoryStore

# Global memory store instance
_memory_store: MemoryStore | None = None


def get_memory_store(workspace_path: str | Path | None = None) -> MemoryStore:
    """Get the memory store instance.

    Args:
        workspace_path: Optional workspace path.

    Returns:
        MemoryStore instance.
    """
    global _memory_store

    if workspace_path is not None:
        return MemoryStore(workspace_path)

    if _memory_store is None:
        _memory_store = MemoryStore()

    return _memory_store


def reset_memory_store() -> None:
    """Reset the cached memory store instance."""
    global _memory_store
    _memory_store = None
