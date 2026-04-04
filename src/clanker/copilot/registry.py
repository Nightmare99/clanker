"""Copilot session registry for persistence."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from clanker.logging import get_logger

logger = get_logger("copilot.registry")

# Session registry file path
COPILOT_SESSIONS_PATH = Path.home() / ".clanker" / "copilot_sessions.json"


def load_session_registry() -> list[dict]:
    """Load the session registry from file.

    Returns:
        List of session info dicts with 'id', 'model', 'created_at'.
    """
    if not COPILOT_SESSIONS_PATH.exists():
        return []
    try:
        with open(COPILOT_SESSIONS_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def save_session_registry(sessions: list[dict]) -> None:
    """Save the session registry to file.

    Args:
        sessions: List of session info dicts.
    """
    try:
        COPILOT_SESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(COPILOT_SESSIONS_PATH, "w") as f:
            json.dump(sessions, f, indent=2)
    except Exception as e:
        logger.warning("Failed to save session registry: %s", e)


def register_session(session_id: str, model: str) -> None:
    """Register a new session in the local registry.

    Args:
        session_id: The session identifier.
        model: The model ID used for the session.
    """
    sessions = load_session_registry()

    # Check if session already exists
    for s in sessions:
        if s["id"] == session_id:
            return  # Already registered

    sessions.insert(0, {
        "id": session_id,
        "model": model,
        "created_at": datetime.now().isoformat(),
    })

    # Keep only last 50 sessions
    sessions = sessions[:50]
    save_session_registry(sessions)


def unregister_session(session_id: str) -> None:
    """Remove a session from the local registry.

    Args:
        session_id: The session identifier to remove.
    """
    sessions = load_session_registry()
    sessions = [s for s in sessions if s["id"] != session_id]
    save_session_registry(sessions)
