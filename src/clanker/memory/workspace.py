"""Workspace-specific storage management for Clanker.

Manages the .clanker directory in the current workspace for storing
conversations, memories, and other workspace-specific data.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


class WorkspaceStorage:
    """Manage workspace-specific .clanker directory and its contents."""

    CLANKER_DIR = ".clanker"
    CONVERSATIONS_DIR = "conversations"
    MEMORIES_FILE = "memories.json"

    def __init__(self, workspace_path: str | Path | None = None):
        """Initialize workspace storage.

        Args:
            workspace_path: Root of the workspace. Defaults to current directory.
        """
        self._workspace = Path(workspace_path or os.getcwd()).resolve()
        self._clanker_dir = self._workspace / self.CLANKER_DIR

    @property
    def workspace_path(self) -> Path:
        """Get the workspace root path."""
        return self._workspace

    @property
    def clanker_dir(self) -> Path:
        """Get the .clanker directory path."""
        return self._clanker_dir

    @property
    def conversations_dir(self) -> Path:
        """Get the conversations directory path."""
        return self._clanker_dir / self.CONVERSATIONS_DIR

    @property
    def memories_file(self) -> Path:
        """Get the memories file path."""
        return self._clanker_dir / self.MEMORIES_FILE

    def ensure_directories(self) -> None:
        """Create the .clanker directory structure if it doesn't exist."""
        self.conversations_dir.mkdir(parents=True, exist_ok=True)

    def is_initialized(self) -> bool:
        """Check if the workspace has been initialized with .clanker."""
        return self._clanker_dir.exists()

    # ─────────────────────────────────────────────────────────────
    # Conversation Storage
    # ─────────────────────────────────────────────────────────────

    def save_conversation(
        self,
        conversation_id: str,
        messages: list[dict],
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Save a conversation to the workspace.

        Args:
            conversation_id: Unique identifier for the conversation.
            messages: List of message dictionaries.
            metadata: Optional metadata (title, created_at, etc.).

        Returns:
            Path to the saved conversation file.
        """
        self.ensure_directories()

        file_path = self.conversations_dir / f"{conversation_id}.json"

        # Build conversation data
        data = {
            "id": conversation_id,
            "messages": messages,
            "metadata": metadata or {},
            "updated_at": datetime.now().isoformat(),
        }

        # Set created_at if not present
        if "created_at" not in data["metadata"]:
            data["metadata"]["created_at"] = datetime.now().isoformat()

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return file_path

    def load_conversation(self, conversation_id: str) -> dict | None:
        """Load a conversation from the workspace.

        Args:
            conversation_id: The conversation ID to load.

        Returns:
            Conversation data dict or None if not found.
        """
        file_path = self.conversations_dir / f"{conversation_id}.json"

        if not file_path.exists():
            return None

        with open(file_path, encoding="utf-8") as f:
            return json.load(f)

    def list_conversations(self) -> list[dict]:
        """List all conversations in the workspace.

        Returns:
            List of conversation summaries (id, title, created_at, message_count).
        """
        if not self.conversations_dir.exists():
            return []

        conversations = []
        for file_path in sorted(
            self.conversations_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            try:
                with open(file_path, encoding="utf-8") as f:
                    data = json.load(f)

                metadata = data.get("metadata", {})
                conversations.append({
                    "id": data.get("id", file_path.stem),
                    "title": metadata.get("title", "Untitled"),
                    "created_at": metadata.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                    "message_count": len(data.get("messages", [])),
                })
            except (json.JSONDecodeError, KeyError):
                # Skip corrupted files
                continue

        return conversations

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation from the workspace.

        Args:
            conversation_id: The conversation ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        file_path = self.conversations_dir / f"{conversation_id}.json"

        if file_path.exists():
            file_path.unlink()
            return True
        return False

    # ─────────────────────────────────────────────────────────────
    # Memories Storage
    # ─────────────────────────────────────────────────────────────

    def load_memories(self) -> list[dict]:
        """Load all memories from the workspace.

        Returns:
            List of memory dictionaries.
        """
        if not self.memories_file.exists():
            return []

        try:
            with open(self.memories_file, encoding="utf-8") as f:
                data = json.load(f)
                return data.get("memories", [])
        except (json.JSONDecodeError, KeyError):
            return []

    def save_memories(self, memories: list[dict]) -> None:
        """Save memories to the workspace.

        Args:
            memories: List of memory dictionaries.
        """
        self.ensure_directories()

        data = {
            "version": 1,
            "updated_at": datetime.now().isoformat(),
            "memories": memories,
        }

        with open(self.memories_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def add_memory(self, memory: dict) -> None:
        """Add a single memory to the workspace.

        Args:
            memory: Memory dictionary to add.
        """
        memories = self.load_memories()
        memories.append(memory)
        self.save_memories(memories)

    def clear_memories(self) -> None:
        """Clear all memories from the workspace."""
        self.save_memories([])


# Global workspace storage instance (lazily initialized)
_workspace_storage: WorkspaceStorage | None = None


def get_workspace_storage(workspace_path: str | Path | None = None) -> WorkspaceStorage:
    """Get the workspace storage instance.

    Args:
        workspace_path: Optional workspace path. Uses cached instance if same path.

    Returns:
        WorkspaceStorage instance.
    """
    global _workspace_storage

    if workspace_path is not None:
        return WorkspaceStorage(workspace_path)

    if _workspace_storage is None:
        _workspace_storage = WorkspaceStorage()

    return _workspace_storage


def reset_workspace_storage() -> None:
    """Reset the cached workspace storage instance."""
    global _workspace_storage
    _workspace_storage = None
