"""Copilot SDK session management with native persistence."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from clanker.logging import get_logger

logger = get_logger("copilot.session")

# Session registry file path
COPILOT_SESSIONS_PATH = Path.home() / ".clanker" / "copilot_sessions.json"


def _load_session_registry() -> list[dict]:
    """Load the session registry from file."""
    if not COPILOT_SESSIONS_PATH.exists():
        return []
    try:
        with open(COPILOT_SESSIONS_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def _save_session_registry(sessions: list[dict]) -> None:
    """Save the session registry to file."""
    try:
        COPILOT_SESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(COPILOT_SESSIONS_PATH, "w") as f:
            json.dump(sessions, f, indent=2)
    except Exception as e:
        logger.warning("Failed to save session registry: %s", e)


def _register_session(session_id: str, model: str) -> None:
    """Register a new session in the local registry."""
    sessions = _load_session_registry()

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
    _save_session_registry(sessions)


def _unregister_session(session_id: str) -> None:
    """Remove a session from the local registry."""
    sessions = _load_session_registry()
    sessions = [s for s in sessions if s["id"] != session_id]
    _save_session_registry(sessions)

# Global session manager instance
_session_manager: CopilotSessionManager | None = None


def get_copilot_session_manager() -> CopilotSessionManager:
    """Get or create the global Copilot session manager."""
    global _session_manager
    if _session_manager is None:
        _session_manager = CopilotSessionManager()
    return _session_manager


def reset_copilot_session_manager() -> None:
    """Reset the global session manager (for testing or cleanup)."""
    global _session_manager
    _session_manager = None


class CopilotSessionManager:
    """Session manager using Copilot SDK's native persistence.

    This manager leverages the SDK's built-in session features:
    - Persistent sessions with custom IDs
    - Infinite sessions with automatic context compaction
    - Session resume across application restarts
    - Session listing and deletion
    """

    def __init__(self):
        self._client: Any | None = None
        self._session: Any | None = None
        self._session_id: str | None = None
        self._current_model: str | None = None
        self._tools: list | None = None
        self._tool_callback: Callable | None = None

    @property
    def session_id(self) -> str | None:
        """Get current session ID."""
        return self._session_id

    @property
    def session(self) -> Any | None:
        """Get current session."""
        return self._session

    async def ensure_client(self) -> Any:
        """Get or create the Copilot client."""
        if self._client is None:
            try:
                from copilot import CopilotClient
                from copilot.types import SubprocessConfig
            except ImportError:
                raise ImportError(
                    "github-copilot-sdk is not installed. "
                    "Install it with: pip install github-copilot-sdk"
                )

            # Ensure token is available
            from clanker.providers.github_copilot import _get_github_token, _load_copilot_token

            token = _get_github_token() or _load_copilot_token()
            if not token:
                raise ValueError(
                    "No Copilot token found. Run '/gh-login' to authenticate."
                )

            # Pass token directly via SubprocessConfig
            config = SubprocessConfig(
                github_token=token,
                use_logged_in_user=False,
            )
            self._client = CopilotClient(config)
            await self._client.start()
            logger.info("Copilot client initialized with explicit token")

        return self._client

    async def create_session(
        self,
        model: str,
        tools: list | None = None,
        system_message: str | None = None,
    ) -> Any:
        """Create a new Copilot session with persistence.

        Args:
            model: The model ID to use.
            tools: List of Copilot Tool objects.
            system_message: Optional system prompt.

        Returns:
            The created session.
        """
        from copilot import PermissionHandler

        client = await self.ensure_client()

        # Generate a meaningful session ID
        self._session_id = f"clanker-{uuid.uuid4().hex[:8]}"
        self._current_model = model
        self._tools = tools

        # Build session config
        session_kwargs = {
            "session_id": self._session_id,
            "model": model,
            "streaming": True,
            "on_permission_request": PermissionHandler.approve_all,
            "infinite_sessions": {
                "enabled": True,
                "background_compaction_threshold": 0.80,
                "buffer_exhaustion_threshold": 0.95,
            },
        }

        # Add tools if provided
        if tools:
            tool_names = [t.name for t in tools]
            session_kwargs["tools"] = tools
            session_kwargs["available_tools"] = tool_names
            logger.info("Creating session with %d tools", len(tools))

        # Add system message if provided
        if system_message:
            session_kwargs["system_message"] = {
                "mode": "replace",
                "content": system_message,
            }

        self._session = await client.create_session(**session_kwargs)
        logger.info("Created Copilot session: %s with model: %s", self._session_id, model)

        # Register in local session registry
        _register_session(self._session_id, model)

        return self._session

    async def resume_session(
        self,
        session_id: str,
        model: str | None = None,
        tools: list | None = None,
    ) -> Any:
        """Resume an existing Copilot session.

        Args:
            session_id: The session ID to resume.
            model: Optional model override.
            tools: Optional tools override.

        Returns:
            The resumed session.
        """
        from copilot import PermissionHandler

        client = await self.ensure_client()

        self._session_id = session_id

        resume_kwargs = {
            "on_permission_request": PermissionHandler.approve_all,
        }

        if model:
            resume_kwargs["model"] = model
            self._current_model = model

        if tools:
            tool_names = [t.name for t in tools]
            resume_kwargs["tools"] = tools
            resume_kwargs["available_tools"] = tool_names
            self._tools = tools

        self._session = await client.resume_session(session_id, **resume_kwargs)
        logger.info("Resumed Copilot session: %s", session_id)

        return self._session

    async def get_or_create_session(
        self,
        model: str,
        tools: list | None = None,
        system_message: str | None = None,
    ) -> Any:
        """Get existing session or create a new one.

        If a session exists and model matches, returns it.
        If model changed, updates the session.
        Otherwise creates a new session.
        """
        if self._session is not None:
            # Check if we need to switch models
            if model != self._current_model:
                logger.info("Switching model from %s to %s", self._current_model, model)
                # Resume with new model
                await self.resume_session(
                    self._session_id,
                    model=model,
                    tools=tools,
                )
            return self._session

        return await self.create_session(model, tools, system_message)

    async def new_session(
        self,
        model: str | None = None,
        tools: list | None = None,
        system_message: str | None = None,
    ) -> Any:
        """Start a fresh session (for /clear command).

        Disconnects current session and creates a new one.
        """
        if self._session is not None:
            try:
                await self._session.disconnect()
            except Exception as e:
                logger.warning("Error disconnecting session: %s", e)

        self._session = None
        self._session_id = None

        return await self.create_session(
            model=model or self._current_model or "gpt-4.1",
            tools=tools or self._tools,
            system_message=system_message,
        )

    async def list_sessions(self) -> list[dict]:
        """List all Copilot sessions from local registry.

        Returns:
            List of session info dicts.
        """
        # Use local registry since SDK only tracks active sessions
        return _load_session_registry()

    async def delete_session(self, session_id: str) -> bool:
        """Delete a Copilot session.

        Args:
            session_id: The session ID to delete.

        Returns:
            True if deleted successfully.
        """
        client = await self.ensure_client()

        try:
            await client.delete_session(session_id)
            logger.info("Deleted session: %s", session_id)
        except Exception as e:
            logger.warning("Failed to delete session from SDK %s: %s", session_id, e)

        # Always remove from local registry
        _unregister_session(session_id)

        # If deleting current session, clear it
        if session_id == self._session_id:
            self._session = None
            self._session_id = None

        return True

    async def send_message(self, prompt: str) -> Any:
        """Send a message to the current session.

        Args:
            prompt: The user's message.

        Returns:
            The session response.
        """
        if self._session is None:
            raise ValueError("No active session. Call create_session first.")

        return await self._session.send_and_wait(prompt)

    async def cleanup(self) -> None:
        """Clean up the session manager."""
        if self._session is not None:
            try:
                await self._session.disconnect()
            except Exception as e:
                logger.warning("Error disconnecting session: %s", e)
            self._session = None

        if self._client is not None:
            try:
                await self._client.stop()
            except Exception as e:
                logger.warning("Error stopping client: %s", e)
            self._client = None

        self._session_id = None
        self._current_model = None
        logger.info("Copilot session manager cleaned up")
