"""Inspectable, workspace-scoped long-term memory with Markdown as the source of truth."""

import os
import re
import tempfile
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from clanker.memory.index import MemoryIndex
from clanker.memory.workspace import get_workspace_storage


class MemorySource(StrEnum):
    """Source of a memory."""

    USER = "user"  # User explicitly asked to remember
    AUTO = "auto"  # Agent auto-generated
    SYSTEM = "system"  # System-generated


class MemoryKind(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    DECISION = "decision"
    EPISODE = "episode"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _normalized(content: str) -> str:
    return " ".join(content.casefold().split())


_STOP_WORDS = {
    "a", "an", "are", "can", "do", "does", "for", "how", "i", "in", "is",
    "me", "my", "of", "on", "our", "run", "the", "to", "tomorrow", "we", "what",
    "where", "which", "with",
}
_CODING_ALIASES = {
    "asynchronous": {"async", "asyncio"},
    "async": {"asynchronous", "asyncio"},
    "tests": {"test", "testing", "pytest"},
    "testing": {"test", "tests", "pytest"},
    "dependencies": {"dependency", "packages"},
}


def _search_terms(query: str) -> set[str]:
    terms = set(re.findall(r"\w+", query.casefold().replace("_", " "))) - _STOP_WORDS
    return terms | {alias for term in terms for alias in _CODING_ALIASES.get(term, ())}


def _looks_sensitive(content: str) -> bool:
    """Reject common credential-shaped values before writing durable memory."""
    return bool(re.search(
        r"(?i)(-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|"
        r"\b(?:password|api[_-]?key|access[_-]?token|secret)\s*[:=]\s*\S+|"
        r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}))",
        content,
    ))


@dataclass
class Memory:
    """A single memory entry."""

    content: str
    source: MemorySource = MemorySource.USER
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    metadata: dict[str, Any] = field(default_factory=dict)
    kind: MemoryKind = MemoryKind.FACT
    scope: str = "workspace"
    pinned: bool = False
    updated_at: str = field(default_factory=_now)
    verified_at: str | None = None
    evidence: str | None = None
    status: str = "active"

    def to_markdown(self) -> str:
        """Convert to markdown with YAML frontmatter."""
        frontmatter = {
            "id": self.id, "source": self.source.value, "created": self.created_at,
            "updated": self.updated_at, "kind": self.kind.value, "scope": self.scope,
            "pinned": self.pinned, "status": self.status, "tags": self.tags,
            "verified": self.verified_at, "evidence": self.evidence,
            "metadata": self.metadata,
        }
        header = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
        return f"---\n{header}\n---\n\n{self.content}\n"

    @classmethod
    def from_markdown(cls, content: str, file_id: str | None = None) -> "Memory":
        """Parse a Memory from markdown with YAML frontmatter."""
        frontmatter: dict[str, Any] = {}
        body = content

        if content.startswith("---\n"):
            parts = content.split("\n---\n", 1)
            if len(parts) == 2:
                frontmatter = yaml.safe_load(parts[0][4:]) or {}
                if not isinstance(frontmatter, dict):
                    raise ValueError("Memory frontmatter must be a mapping")
                body = parts[1].strip()

        def date_value(key: str, fallback: str | None = None) -> str | None:
            value = frontmatter.get(key, fallback)
            return value.isoformat() if isinstance(value, date) else value

        return cls(
            id=frontmatter.get("id", file_id or str(uuid.uuid4())[:8]),
            content=body,
            source=MemorySource(frontmatter.get("source", "user")),
            tags=frontmatter.get("tags", []) if isinstance(frontmatter.get("tags"), list) else [],
            created_at=date_value("created", _now()) or _now(),
            updated_at=date_value("updated", date_value("created", _now())) or _now(),
            verified_at=date_value("verified"),
            evidence=frontmatter.get("evidence"),
            kind=MemoryKind(frontmatter.get("kind", "fact")),
            scope=frontmatter.get("scope", "workspace"),
            pinned=bool(frontmatter.get("pinned", False)),
            status=frontmatter.get("status", "active"),
            metadata=frontmatter.get("metadata") or {},
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "content": self.content,
            "source": self.source.value,
            "tags": self.tags,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "kind": self.kind.value,
            "scope": self.scope,
            "pinned": self.pinned,
            "updated_at": self.updated_at,
            "verified_at": self.verified_at,
            "evidence": self.evidence,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Memory":
        """Create a Memory from a dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            content=data["content"],
            source=MemorySource(data.get("source", "user")),
            tags=data.get("tags", []),
            created_at=data.get("created_at", datetime.now().isoformat()),
            metadata=data.get("metadata", {}),
            kind=MemoryKind(data.get("kind", "fact")),
            scope=data.get("scope", "workspace"),
            pinned=bool(data.get("pinned", False)),
            updated_at=data.get("updated_at", data.get("created_at", _now())),
            verified_at=data.get("verified_at"),
            evidence=data.get("evidence"),
            status=data.get("status", "active"),
        )


class MemoryStore:
    """Markdown-based memory store."""

    def __init__(self, workspace_path: str | Path | None = None, *, include_global: bool = True):
        """Initialize the memory store.

        Args:
            workspace_path: Optional workspace path. Defaults to current directory.
        """
        self._storage = get_workspace_storage(workspace_path)
        self._memories_dir: Path | None = None
        self._include_global = include_global
        self._index = MemoryIndex(self._storage.clanker_dir / "memory-index.sqlite")

    def _get_memories_dir(self) -> Path:
        """Get the memories directory path."""
        if self._memories_dir is None:
            self._memories_dir = self._storage.clanker_dir / "memories"
            self._memories_dir.mkdir(parents=True, exist_ok=True)
        return self._memories_dir

    def _get_memory_path(self, memory_id: str, scope: str = "workspace") -> Path:
        """Get the path for a specific memory file."""
        if not re.fullmatch(r"[a-f0-9]{8,32}", memory_id):
            raise ValueError("Invalid memory ID")
        if scope == "global":
            return Path.home() / ".clanker" / "memories" / f"{memory_id}.md"
        if scope != "workspace":
            raise ValueError("Memory scope must be workspace or global")
        return self._get_memories_dir() / f"{memory_id}.md"

    def _iter_paths(self) -> Iterator[Path]:
        yield from self._get_memories_dir().glob("*.md")
        global_dir = Path.home() / ".clanker" / "memories"
        if self._include_global and global_dir.is_dir():
            yield from global_dir.glob("*.md")

    def _save(self, memory: Memory) -> None:
        path = self._get_memory_path(memory.id, memory.scope)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".memory-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(memory.to_markdown())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _evidence_file(self, evidence: str | None) -> Path | None:
        if not evidence or "://" in evidence:
            return None
        candidate = (self._storage.workspace_path / evidence).resolve()
        if not candidate.is_relative_to(self._storage.workspace_path):
            return None
        return candidate if candidate.is_file() else None

    def _record_evidence_revision(self, memory: Memory) -> None:
        path = self._evidence_file(memory.evidence)
        if path:
            memory.metadata["evidence_mtime_ns"] = path.stat().st_mtime_ns
        else:
            memory.metadata.pop("evidence_mtime_ns", None)

    def needs_verification(self, memory: Memory) -> bool:
        """Report whether a cited repository file changed since verification."""
        baseline = memory.metadata.get("evidence_mtime_ns")
        if baseline is None:
            return False
        path = self._evidence_file(memory.evidence)
        return path is None or path.stat().st_mtime_ns != baseline

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
        kind: MemoryKind | str = MemoryKind.FACT,
        scope: str = "workspace",
        evidence: str | None = None,
        pinned: bool = False,
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
        content = content.strip()
        if not content:
            raise ValueError("Memory content cannot be empty")
        if _looks_sensitive(content):
            raise ValueError("Credential-like values cannot be stored in memory")
        if scope not in ("workspace", "global"):
            raise ValueError("Memory scope must be workspace or global")
        for existing in self.list_all(limit=None):
            if (existing.scope == scope and existing.status == "active"
                    and _normalized(existing.content) == _normalized(content)):
                changed = False
                if source == MemorySource.USER and existing.source != MemorySource.USER:
                    existing.source = MemorySource.USER
                    changed = True
                if existing.kind != MemoryKind(kind):
                    existing.kind = MemoryKind(kind)
                    changed = True
                if tags:
                    merged_tags = list(dict.fromkeys([*existing.tags, *tags]))
                    if merged_tags != existing.tags:
                        existing.tags = merged_tags
                        changed = True
                if pinned and not existing.pinned:
                    existing.pinned = True
                    changed = True
                if evidence and evidence != existing.evidence:
                    existing.evidence = evidence
                    self._record_evidence_revision(existing)
                    changed = True
                if changed:
                    existing.updated_at = _now()
                    self._save(existing)
                return existing

        memory = Memory(
            content=content,
            source=MemorySource(source),
            tags=tags or [],
            metadata=metadata or {},
            kind=MemoryKind(kind),
            scope=scope,
            evidence=evidence,
            pinned=pinned,
        )
        self._record_evidence_revision(memory)
        self._save(memory)
        return memory

    def get(self, memory_id: str) -> Memory | None:
        """Get a specific memory by ID.

        Args:
            memory_id: The memory ID.

        Returns:
            The Memory or None if not found.
        """
        try:
            for scope in ("workspace", "global"):
                path = self._get_memory_path(memory_id, scope)
                if path.exists():
                    return self._load_memory(path)
        except ValueError:
            return None
        return None

    def update(self, memory_id: str, **changes: Any) -> Memory | None:
        """Edit a memory while preserving its ID, provenance, and creation time."""
        memory = self.get(memory_id)
        if memory is None:
            return None
        allowed = {"content", "tags", "kind", "pinned", "status", "evidence", "verified_at"}
        if invalid := changes.keys() - allowed:
            raise ValueError(f"Unsupported memory fields: {', '.join(sorted(invalid))}")
        if "content" in changes:
            content = str(changes["content"]).strip()
            if not content or _looks_sensitive(content):
                raise ValueError("Memory content is empty or contains credential-like values")
            changes["content"] = content
        if "kind" in changes:
            changes["kind"] = MemoryKind(changes["kind"])
        if "status" in changes and changes["status"] not in ("active", "stale"):
            raise ValueError("Memory status must be active or stale")
        for key, value in changes.items():
            setattr(memory, key, value)
        if changes.keys() & {"content", "evidence", "verified_at"}:
            self._record_evidence_revision(memory)
        memory.updated_at = _now()
        self._save(memory)
        return memory

    def supersede(self, memory_id: str, replacement: str, **kwargs: Any) -> Memory:
        """Retain the old assertion as stale provenance and write its replacement."""
        old = self.get(memory_id)
        if old is None:
            raise ValueError("Memory not found")
        if _normalized(old.content) == _normalized(replacement):
            return self.update(
                memory_id, verified_at=_now(),
                evidence=kwargs.get("evidence") or old.evidence,
            ) or old
        new = self.add(
            replacement, source=old.source, tags=list(old.tags), kind=old.kind,
            scope=old.scope, evidence=kwargs.get("evidence"), pinned=old.pinned,
            metadata={"supersedes": memory_id},
        )
        self.update(memory_id, status="stale")
        return new

    def list_all(self, limit: int | None = 100) -> list[Memory]:
        """List all memories.

        Args:
            limit: Maximum number of memories to return.

        Returns:
            List of all memories, newest first.
        """
        memories = []
        for path in self._iter_paths():
            memory = self._load_memory(path)
            if memory:
                memories.append(memory)

        # Sort by created_at descending
        memories.sort(key=lambda m: m.created_at, reverse=True)
        return memories[:limit] if limit is not None else memories

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
        memories = [
            m for m in self.list_all(limit=None)
            if m.status == "active" and not self.needs_verification(m)
        ]
        if tags:
            wanted = {tag.casefold() for tag in tags}
            memories = [m for m in memories if wanted & {t.casefold() for t in m.tags}]

        query_words = _search_terms(query or "")
        if query and not query_words:
            return []
        fts_scores: dict[str, float] | None = None
        if query_words:
            documents = [
                (m.id, self._get_memory_path(m.id, m.scope), m.content, " ".join(m.tags))
                for m in memories
            ]
            fts_scores = self._index.search(" ".join(sorted(query_words)), documents)

        ranked: list[tuple[float, Memory]] = []
        for memory in memories:
            text = f"{memory.content} {' '.join(memory.tags)}".casefold().replace("_", " ")
            overlaps = query_words & set(re.findall(r"\w+", text))
            if (query_words and not overlaps and (fts_scores is None or memory.id not in fts_scores)
                    and not (memory.pinned and memory.kind == MemoryKind.PREFERENCE
                             and memory.scope == "global")):
                continue
            score = len(overlaps) * 3.0
            if query and query.casefold() in text:
                score += 5.0
            if fts_scores is not None and memory.id in fts_scores:
                score += max(0.0, min(10.0, fts_scores[memory.id] * 1_000_000))
            if memory.pinned:
                score += 8.0
            if memory.source == MemorySource.USER:
                score += 2.0
            if memory.verified_at:
                score += 1.0
            if tags:
                score += 10.0
            ranked.append((score, memory))

        ranked.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
        return [memory for _, memory in ranked[:max(0, n_results)]]

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
        try:
            for scope in ("workspace", "global"):
                path = self._get_memory_path(memory_id, scope)
                if path.exists():
                    path.unlink()
                    return True
        except ValueError:
            return False
        return False

    def clear(self) -> None:
        """Clear all memories."""
        for path in self._get_memories_dir().glob("*.md"):
            path.unlink()

    def count(self) -> int:
        """Get the number of memories."""
        return sum(1 for _ in self._iter_paths())

    def get_all_tags(self) -> list[str]:
        """Get all unique tags across all memories.

        Returns:
            Sorted list of unique tags.
        """
        tags = set()
        for memory in self.list_all(limit=None):
            tags.update(memory.tags)
        return sorted(tags)

    def get_memories_summary(self) -> str:
        """Get a summary of available memories and their tags.

        Returns:
            Formatted summary string for the agent.
        """
        memories = self.list_all(limit=None)
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

    def get_relevant_context(
        self, query: str, tags: list[str] | None = None,
        max_memories: int = 5, token_budget: int = 800,
    ) -> str:
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

        lines = ["## Relevant Memories", "These notes may be stale. Verify consequential facts against the repository.", ""]
        used = sum(len(line) for line in lines) // 4

        for memory in memories:
            remaining = max(0, token_budget - used)
            if remaining < 30:
                break
            details = f"[{memory.id}; {memory.kind.value}; {memory.scope}; {memory.source.value}]"
            if memory.evidence:
                details += f" evidence: {memory.evidence}"
            body = " ".join(memory.content.split())
            line = f"- {details} {body[: max(0, remaining * 4 - len(details) - 4)]}"
            lines.append(line)
            used += len(line) // 4

        return "\n".join(lines) if len(lines) > 3 else ""


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
