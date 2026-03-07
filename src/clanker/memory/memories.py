"""Vector-based memories system for Clanker using FAISS.

Stores memories as markdown documents in a local vector database for RAG retrieval.
Memories persist across conversations and are automatically retrieved based on context.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

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

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
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


class VectorMemoryStore:
    """Vector-based memory store using FAISS for RAG retrieval."""

    def __init__(self, workspace_path: str | Path | None = None):
        """Initialize the vector memory store.

        Args:
            workspace_path: Optional workspace path. Defaults to current directory.
        """
        self._storage = get_workspace_storage(workspace_path)
        self._embedder = None
        self._index = None
        self._memories: list[Memory] = []
        self._loaded = False

    def _get_db_path(self) -> Path:
        """Get the memory database storage path."""
        return self._storage.clanker_dir / "memory_db"

    def _get_index_path(self) -> Path:
        """Get the FAISS index file path."""
        return self._get_db_path() / "index.faiss"

    def _get_memories_path(self) -> Path:
        """Get the memories JSON file path."""
        return self._get_db_path() / "memories.json"

    def _ensure_embedder(self):
        """Ensure the sentence transformer model is loaded."""
        if self._embedder is None:
            import os
            import sys
            from sentence_transformers import SentenceTransformer

            # Suppress model loading output at file descriptor level
            # (catches tqdm progress bars that write directly to fd)
            try:
                stdout_fd = sys.stdout.fileno()
                stderr_fd = sys.stderr.fileno()
                saved_stdout = os.dup(stdout_fd)
                saved_stderr = os.dup(stderr_fd)

                devnull = os.open(os.devnull, os.O_WRONLY)
                os.dup2(devnull, stdout_fd)
                os.dup2(devnull, stderr_fd)
                os.close(devnull)

                try:
                    self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
                finally:
                    os.dup2(saved_stdout, stdout_fd)
                    os.dup2(saved_stderr, stderr_fd)
                    os.close(saved_stdout)
                    os.close(saved_stderr)
            except (OSError, ValueError):
                # If we can't redirect (e.g., no real stdout), just load normally
                self._embedder = SentenceTransformer("all-MiniLM-L6-v2")

        return self._embedder

    def _embed(self, texts: list[str]) -> np.ndarray:
        """Generate embeddings for texts."""
        embedder = self._ensure_embedder()
        return embedder.encode(texts, convert_to_numpy=True, show_progress_bar=False)

    def _load(self) -> None:
        """Load memories and index from disk."""
        if self._loaded:
            return

        memories_path = self._get_memories_path()
        index_path = self._get_index_path()

        if memories_path.exists():
            with open(memories_path, encoding="utf-8") as f:
                data = json.load(f)
                self._memories = [Memory.from_dict(m) for m in data.get("memories", [])]

        if index_path.exists() and self._memories:
            import faiss
            self._index = faiss.read_index(str(index_path))
        elif self._memories:
            # Rebuild index if memories exist but index doesn't
            self._rebuild_index()

        self._loaded = True

    def _save(self) -> None:
        """Save memories and index to disk."""
        self._storage.ensure_directories()
        db_path = self._get_db_path()
        db_path.mkdir(parents=True, exist_ok=True)

        # Save memories as JSON
        memories_path = self._get_memories_path()
        data = {
            "version": 1,
            "updated_at": datetime.now().isoformat(),
            "memories": [m.to_dict() for m in self._memories],
        }
        with open(memories_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Save FAISS index
        if self._index is not None:
            import faiss
            faiss.write_index(self._index, str(self._get_index_path()))

    def _rebuild_index(self) -> None:
        """Rebuild the FAISS index from current memories."""
        if not self._memories:
            self._index = None
            return

        import faiss

        # Generate embeddings for all memories
        texts = [m.content for m in self._memories]
        embeddings = self._embed(texts)

        # Create FAISS index (L2 distance)
        dimension = embeddings.shape[1]
        self._index = faiss.IndexFlatL2(dimension)
        self._index.add(embeddings.astype(np.float32))

    def add(
        self,
        content: str,
        source: MemorySource = MemorySource.USER,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Memory:
        """Add a new memory to the vector store.

        Args:
            content: The memory content (markdown supported).
            source: Source of the memory.
            tags: Optional tags for categorization.
            metadata: Optional additional metadata.

        Returns:
            The created Memory.
        """
        self._load()

        memory = Memory(
            content=content,
            source=source,
            tags=tags or [],
            metadata=metadata or {},
        )

        self._memories.append(memory)

        # Add to FAISS index
        embedding = self._embed([content])

        import faiss
        if self._index is None:
            dimension = embedding.shape[1]
            self._index = faiss.IndexFlatL2(dimension)

        self._index.add(embedding.astype(np.float32))

        self._save()
        return memory

    def search(
        self,
        query: str,
        n_results: int = 5,
        tags: list[str] | None = None,
    ) -> list[Memory]:
        """Search memories using semantic similarity (RAG).

        Args:
            query: Natural language query for semantic search.
            n_results: Maximum number of results to return.
            tags: Optional tags to filter by.

        Returns:
            List of matching memories, ordered by relevance.
        """
        self._load()

        if not self._memories or self._index is None:
            return []

        # Generate query embedding
        query_embedding = self._embed([query])

        # Search FAISS index
        k = min(n_results * 2, len(self._memories))  # Get more results for filtering
        distances, indices = self._index.search(query_embedding.astype(np.float32), k)

        results = []
        for i, idx in enumerate(indices[0]):
            if idx < 0 or idx >= len(self._memories):
                continue

            memory = self._memories[idx]

            # Filter by tags if specified
            if tags and not any(t in memory.tags for t in tags):
                continue

            results.append(memory)

            if len(results) >= n_results:
                break

        return results

    def get(self, memory_id: str) -> Memory | None:
        """Get a specific memory by ID.

        Args:
            memory_id: The memory ID.

        Returns:
            The Memory or None if not found.
        """
        self._load()

        for memory in self._memories:
            if memory.id == memory_id:
                return memory
        return None

    def list_all(self, limit: int = 100) -> list[Memory]:
        """List all memories.

        Args:
            limit: Maximum number of memories to return.

        Returns:
            List of all memories, newest first.
        """
        self._load()

        # Sort by created_at descending
        sorted_memories = sorted(self._memories, key=lambda m: m.created_at, reverse=True)
        return sorted_memories[:limit]

    def delete(self, memory_id: str) -> bool:
        """Delete a memory by ID.

        Args:
            memory_id: The memory ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        self._load()

        for i, memory in enumerate(self._memories):
            if memory.id == memory_id:
                self._memories.pop(i)
                # Rebuild index after deletion
                self._rebuild_index()
                self._save()
                return True
        return False

    def clear(self) -> None:
        """Clear all memories."""
        self._memories = []
        self._index = None
        self._save()

    def count(self) -> int:
        """Get the number of memories."""
        self._load()
        return len(self._memories)

    def get_relevant_context(self, query: str, max_memories: int = 5) -> str:
        """Get relevant memories formatted for injection into context.

        Uses RAG to find the most relevant memories for the current query.

        Args:
            query: The current conversation context/query.
            max_memories: Maximum number of memories to include.

        Returns:
            Formatted string of relevant memories for the system prompt.
        """
        if self.count() == 0:
            return ""

        memories = self.search(query, n_results=max_memories)

        if not memories:
            return ""

        lines = ["## Relevant Workspace Memories", ""]
        lines.append("The following remembered information may be relevant:")
        lines.append("")

        for memory in memories:
            tags_str = f" [tags: {', '.join(memory.tags)}]" if memory.tags else ""
            # Format as markdown blockquote for clarity
            content_lines = memory.content.strip().split("\n")
            if len(content_lines) == 1:
                lines.append(f"- {memory.content}{tags_str}")
            else:
                lines.append(f"- **Memory ({memory.id})**:{tags_str}")
                for line in content_lines:
                    lines.append(f"  {line}")

        return "\n".join(lines)


# Backwards compatibility alias
MemoryStore = VectorMemoryStore

# Global memory store instance
_memory_store: VectorMemoryStore | None = None


def get_memory_store(workspace_path: str | Path | None = None) -> VectorMemoryStore:
    """Get the memory store instance.

    Args:
        workspace_path: Optional workspace path.

    Returns:
        VectorMemoryStore instance.
    """
    global _memory_store

    if workspace_path is not None:
        return VectorMemoryStore(workspace_path)

    if _memory_store is None:
        _memory_store = VectorMemoryStore()

    return _memory_store


def reset_memory_store() -> None:
    """Reset the cached memory store instance."""
    global _memory_store
    _memory_store = None
