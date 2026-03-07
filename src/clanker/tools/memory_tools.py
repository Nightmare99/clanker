"""Memory tools for Clanker agent.

These tools allow the agent to store and recall memories using vector similarity search.
Memories are stored in a local ChromaDB instance and retrieved via RAG.
"""

from langchain_core.tools import tool

from clanker.memory.memories import MemorySource, get_memory_store


@tool
def remember(content: str, tags: str = "", auto: bool = False) -> dict:
    """Store information in workspace memory for future conversations.

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

    Returns:
        Confirmation with memory ID.
    """
    store = get_memory_store()

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    source = MemorySource.AUTO if auto else MemorySource.USER

    memory = store.add(
        content=content,
        source=source,
        tags=tag_list,
    )

    return {
        "ok": True,
        "message": f"Stored in memory: {content[:60]}{'...' if len(content) > 60 else ''}",
        "memory_id": memory.id,
        "tags": tag_list,
    }


@tool
def recall(query: str, tags: str = "", n_results: int = 5) -> dict:
    """Search memories using semantic similarity (RAG retrieval).

    This tool uses vector similarity to find relevant memories based on meaning,
    not just keyword matching. Use natural language queries.

    Args:
        query: Natural language description of what you're looking for.
               Be descriptive - the search is semantic, not keyword-based.
        tags: Optional comma-separated tags to filter results.
        n_results: Maximum number of memories to return (default: 5).

    Returns:
        List of relevant memories with their content and metadata.
    """
    store = get_memory_store()

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
            }
            for m in memories
        ],
    }


@tool
def forget(memory_id: str) -> dict:
    """Delete a specific memory from the workspace.

    Args:
        memory_id: The ID of the memory to delete.

    Returns:
        Confirmation of deletion.
    """
    store = get_memory_store()

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
def list_memories(limit: int = 20) -> dict:
    """List all stored memories in the workspace.

    Args:
        limit: Maximum number of memories to list (default: 20).

    Returns:
        List of all memories with summaries.
    """
    store = get_memory_store()

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
            }
            for m in memories
        ],
    }
