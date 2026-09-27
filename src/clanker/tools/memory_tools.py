"""Memory tools for Clanker agent.

These tools allow the agent to store and recall memories using tags and keywords.
Memories are stored as markdown files with YAML frontmatter for tags.
"""

from typing import Any

from langchain_core.tools import tool

from clanker.execution import memory_directory
from clanker.memory.memories import MemoryKind, MemorySource, get_memory_store


@tool
def remember(
    content: str, tags: str = "", auto: bool = False,
    kind: str = "fact", scope: str = "workspace", evidence: str = "",
) -> dict[str, Any]:
    """Store durable information for future conversations.

    IMPORTANT: You should PROACTIVELY use this tool to remember useful information!

    Use this tool when:
    - User explicitly asks to remember something
    - You discover project conventions, patterns, or architecture worth preserving
    - You learn user preferences (coding style, frameworks, tools they prefer)
    - You find important configuration details or environment setup
    - You encounter recurring issues and their solutions
    - You identify key project decisions or constraints

    The content supports markdown formatting for structured information.

    Args:
        content: The information to remember. Use markdown for structure.
                 Be detailed - include context, reasoning, and specifics.
        tags: Comma-separated tags for categorization.
              Examples: "preference", "architecture", "convention", "config", "issue"
        auto: Set to true when auto-generating memories (vs user-requested).
        kind: fact, preference, decision, or episode.
        scope: workspace by default; global only for explicit cross-project preferences.
        evidence: Repository path, conversation ID, or URL supporting the memory.

    Returns:
        Confirmation with memory ID.
    """
    store = get_memory_store(memory_directory())

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    source = MemorySource.AUTO if auto else MemorySource.USER

    try:
        memory = store.add(
            content=content, source=source, tags=tag_list,
            kind=MemoryKind(kind), scope=scope, evidence=evidence or None,
        )
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}

    return {
        "ok": True,
        "message": f"Stored in memory: {content[:60]}{'...' if len(content) > 60 else ''}",
        "memory_id": memory.id,
        "tags": tag_list,
        "scope": memory.scope,
    }


@tool
def recall(query: str = "", tags: str = "", n_results: int = 5) -> dict[str, Any]:
    """Search memories by tags and keywords.

    Keywords search content and tags; explicit tags can narrow the results.

    Args:
        query: Keywords to search for in memory content.
        tags: Comma-separated tags to filter by.
              Examples: "preference", "architecture", "convention", "config", "issue"
        n_results: Maximum number of memories to return (default: 5).

    Returns:
        List of relevant memories with their content and metadata.
    """
    store = get_memory_store(memory_directory())

    if store.count() == 0:
        return {
            "ok": True,
            "found": False,
            "message": "No memories stored yet.",
            "memories": [],
        }

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    memories = store.search(query, n_results=n_results, tags=tag_list)

    if not memories:
        return {
            "ok": True,
            "found": False,
            "message": f"No memories found matching: {query}",
            "memories": [],
        }

    return {
        "ok": True,
        "found": True,
        "count": len(memories),
        "memories": [
            {
                "id": m.id,
                "content": m.content,
                "tags": m.tags,
                "source": m.source.value,
                "created_at": m.created_at,
                "kind": m.kind.value,
                "scope": m.scope,
                "evidence": m.evidence,
                "verified_at": m.verified_at,
            }
            for m in memories
        ],
    }


@tool
def forget(memory_id: str) -> dict[str, Any]:
    """Delete a specific workspace or global memory.

    Args:
        memory_id: The ID of the memory to delete.

    Returns:
        Confirmation of deletion.
    """
    store = get_memory_store(memory_directory())

    if store.delete(memory_id):
        return {
            "ok": True,
            "message": f"Memory {memory_id} has been deleted.",
        }
    else:
        return {
            "ok": False,
            "message": f"Memory {memory_id} not found.",
        }


@tool
def list_memories(limit: int = 20) -> dict[str, Any]:
    """List stored workspace and global memories.

    Args:
        limit: Maximum number of memories to list (default: 20).

    Returns:
        List of all memories with summaries.
    """
    store = get_memory_store(memory_directory())

    if store.count() == 0:
        return {
            "ok": True,
            "count": 0,
            "message": "No memories stored yet.",
            "memories": [],
        }

    memories = store.list_all(limit=limit)

    return {
        "ok": True,
        "count": len(memories),
        "total": store.count(),
        "memories": [
            {
                "id": m.id,
                "content": m.content[:100] + "..." if len(m.content) > 100 else m.content,
                "tags": m.tags,
                "source": m.source.value,
                "kind": m.kind.value,
                "scope": m.scope,
                "pinned": m.pinned,
                "status": m.status,
            }
            for m in memories
        ],
    }


@tool
def revise_memory(memory_id: str, replacement: str, evidence: str = "") -> dict[str, Any]:
    """Replace an outdated memory, preserving the old record as stale provenance.

    Args:
        memory_id: ID of the memory that is no longer correct.
        replacement: Corrected durable fact or preference.
        evidence: Repository path, conversation ID, or other supporting reference.
    """
    store = get_memory_store(memory_directory())
    try:
        memory = store.supersede(memory_id, replacement, evidence=evidence or None)
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "memory_id": memory.id, "supersedes": memory_id}
