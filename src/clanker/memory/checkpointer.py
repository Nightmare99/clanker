"""Checkpointer setup for session persistence."""

import uuid
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from clanker.config import get_settings


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


def create_checkpointer():
    """Create a checkpointer for session persistence.

    Currently uses in-memory storage. Future versions could implement
    SQLite or file-based persistence.

    Returns:
        A LangGraph checkpointer instance.
    """
    # For now, use in-memory saver
    # Future: Implement SQLite-based persistence
    return MemorySaver()


def generate_session_id() -> str:
    """Generate a new unique session ID."""
    return str(uuid.uuid4())[:8]


class SessionManager:
    """Manage session lifecycle and configuration."""

    def __init__(self):
        self._current_session: str | None = None
        self._checkpointer = None

    @property
    def session_id(self) -> str:
        """Get current session ID, creating one if needed."""
        if self._current_session is None:
            self._current_session = generate_session_id()
        return self._current_session

    @property
    def checkpointer(self):
        """Get or create the checkpointer."""
        if self._checkpointer is None:
            self._checkpointer = create_checkpointer()
        return self._checkpointer

    def new_session(self) -> str:
        """Start a new session."""
        self._current_session = generate_session_id()
        return self._current_session

    def resume_session(self, session_id: str) -> None:
        """Resume an existing session."""
        self._current_session = session_id

    def get_config(self) -> dict:
        """Get the configuration for graph invocation."""
        return {
            "configurable": {"thread_id": self.session_id},
            "recursion_limit": 100,
        }
