"""Checkpointer setup for session persistence."""

import json
import uuid
from datetime import datetime
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from clanker.config import get_settings
from clanker.memory.workspace import get_workspace_storage


def get_session_path(session_id: str | None = None) -> Path:
    """Get the path for storing session data.

    Args:
        session_id: Optional session ID. Generates new one if not provided.

    Returns:
        Path to the session storage directory.
    """
    settings = get_settings()
    storage_path = settings.memory.storage_path

    if session_id is None:
        session_id = str(uuid.uuid4())[:8]

    return storage_path / session_id


def create_checkpointer(use_sqlite: bool = True, workspace_path: str | None = None):
    """Create a checkpointer for session persistence.

    Args:
        use_sqlite: If True, use SQLite for persistence. Otherwise, in-memory.
        workspace_path: Optional workspace path for SQLite storage.

    Returns:
        A LangGraph checkpointer instance (MemorySaver).
        Cross-session persistence is handled by JSON snapshots in SessionManager.
    """
    # Use MemorySaver for LangGraph state within a session
    # Cross-session persistence is handled by JSON-based conversation snapshots
    return MemorySaver()


def generate_session_id() -> str:
    """Generate a new unique session ID."""
    return str(uuid.uuid4())[:8]


def _message_to_dict(msg) -> dict:
    """Convert a LangChain message to a serializable dict."""
    msg_type = "unknown"
    if isinstance(msg, HumanMessage):
        msg_type = "human"
    elif isinstance(msg, AIMessage):
        msg_type = "ai"
    elif isinstance(msg, SystemMessage):
        msg_type = "system"
    elif isinstance(msg, ToolMessage):
        msg_type = "tool"

    result = {
        "type": msg_type,
        "content": msg.content if isinstance(msg.content, str) else str(msg.content),
    }

    # Include tool calls for AI messages
    if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
        result["tool_calls"] = [
            {"name": tc.get("name", ""), "args": tc.get("args", {})}
            for tc in msg.tool_calls
        ]

    return result


def _dict_to_message(data: dict):
    """Convert a dict back to a LangChain message."""
    msg_type = data.get("type", "unknown")
    content = data.get("content", "")

    if msg_type == "human":
        return HumanMessage(content=content)
    elif msg_type == "ai":
        return AIMessage(content=content)
    elif msg_type == "system":
        return SystemMessage(content=content)
    elif msg_type == "tool":
        return ToolMessage(content=content, tool_call_id=data.get("tool_call_id", ""))
    else:
        return HumanMessage(content=content)


class SessionManager:
    """Manage session lifecycle and configuration."""

    def __init__(self, workspace_path: str | None = None):
        """Initialize the session manager.

        Args:
            workspace_path: Optional workspace path for storage.
        """
        self._current_session: str | None = None
        self._checkpointer = None
        self._workspace_path = workspace_path
        self._storage = get_workspace_storage(workspace_path)
        self._session_title: str | None = None
        self._session_created: str | None = None

    @property
    def session_id(self) -> str:
        """Get current session ID, creating one if needed."""
        if self._current_session is None:
            self._current_session = generate_session_id()
            self._session_created = datetime.now().isoformat()
        return self._current_session

    @property
    def checkpointer(self):
        """Get or create the checkpointer."""
        if self._checkpointer is None:
            self._checkpointer = create_checkpointer(
                use_sqlite=True,
                workspace_path=self._workspace_path,
            )
        return self._checkpointer

    def new_session(self) -> str:
        """Start a new session."""
        self._current_session = generate_session_id()
        self._session_created = datetime.now().isoformat()
        self._session_title = None
        return self._current_session

    def resume_session(self, session_id: str) -> None:
        """Resume an existing session."""
        self._current_session = session_id
        # Load metadata if available
        metadata = self._load_session_metadata(session_id)
        if metadata:
            self._session_title = metadata.get("title")
            self._session_created = metadata.get("created_at")

    def get_config(self) -> dict:
        """Get the configuration for graph invocation."""
        return {
            "configurable": {"thread_id": self.session_id},
            "recursion_limit": 100,
        }

    def set_title(self, title: str) -> None:
        """Set the title for the current session."""
        self._session_title = title
        self._save_session_metadata()

    def _get_metadata_path(self, session_id: str) -> Path:
        """Get the path to session metadata file."""
        return self._storage.conversations_dir / f"{session_id}.meta.json"

    def _load_session_metadata(self, session_id: str) -> dict | None:
        """Load metadata for a session."""
        meta_path = self._get_metadata_path(session_id)
        if meta_path.exists():
            with open(meta_path, encoding="utf-8") as f:
                return json.load(f)
        return None

    def _save_session_metadata(self) -> None:
        """Save metadata for the current session."""
        if self._current_session is None:
            return

        self._storage.ensure_directories()
        meta_path = self._get_metadata_path(self._current_session)

        metadata = {
            "id": self._current_session,
            "title": self._session_title or "Untitled",
            "created_at": self._session_created or datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

    def save_conversation_snapshot(self, messages: list) -> None:
        """Save a snapshot of the conversation with messages.

        Args:
            messages: List of LangChain messages.
        """
        if not messages:
            return

        # Auto-generate title from first user message if not set
        if not self._session_title:
            for msg in messages:
                if isinstance(msg, HumanMessage):
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    self._session_title = content[:50] + ("..." if len(content) > 50 else "")
                    break

        self._storage.ensure_directories()

        # Save messages to JSON for easy viewing
        conv_path = self._storage.conversations_dir / f"{self.session_id}.json"

        data = {
            "id": self.session_id,
            "title": self._session_title or "Untitled",
            "created_at": self._session_created or datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "message_count": len(messages),
            "messages": [_message_to_dict(m) for m in messages],
        }

        with open(conv_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Also save metadata
        self._save_session_metadata()

    def list_sessions(self) -> list[dict]:
        """List all sessions in the workspace.

        Returns:
            List of session summaries.
        """
        if not self._storage.conversations_dir.exists():
            return []

        sessions = []

        # Look for .meta.json files
        for meta_path in sorted(
            self._storage.conversations_dir.glob("*.meta.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            try:
                with open(meta_path, encoding="utf-8") as f:
                    metadata = json.load(f)

                # Try to get message count from conversation file
                conv_path = meta_path.with_suffix("").with_suffix(".json")
                message_count = 0
                if conv_path.exists():
                    with open(conv_path, encoding="utf-8") as f:
                        conv_data = json.load(f)
                        message_count = conv_data.get("message_count", 0)

                sessions.append({
                    "id": metadata.get("id", meta_path.stem.replace(".meta", "")),
                    "title": metadata.get("title", "Untitled"),
                    "created_at": metadata.get("created_at", ""),
                    "updated_at": metadata.get("updated_at", ""),
                    "message_count": message_count,
                })
            except (json.JSONDecodeError, KeyError):
                continue

        return sessions

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its data.

        Args:
            session_id: The session ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        deleted = False

        # Delete metadata file
        meta_path = self._get_metadata_path(session_id)
        if meta_path.exists():
            meta_path.unlink()
            deleted = True

        # Delete conversation file
        conv_path = self._storage.conversations_dir / f"{session_id}.json"
        if conv_path.exists():
            conv_path.unlink()
            deleted = True

        return deleted

    def get_session_messages(self, session_id: str) -> list | None:
        """Get messages from a saved session.

        Args:
            session_id: The session ID.

        Returns:
            List of messages or None if not found.
        """
        conv_path = self._storage.conversations_dir / f"{session_id}.json"

        if not conv_path.exists():
            return None

        with open(conv_path, encoding="utf-8") as f:
            data = json.load(f)

        return [_dict_to_message(m) for m in data.get("messages", [])]
