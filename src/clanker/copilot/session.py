"""Copilot SDK session management with native persistence."""

from __future__ import annotations

import uuid
from typing import Any, Callable

from clanker.logging import get_logger
from clanker.copilot.registry import register_session, unregister_session, load_session_registry

logger = get_logger("copilot.session")


async def _query_mcp_tool_names(mcp_servers: dict | None) -> list[str]:
    """Query MCP servers to get tool names dynamically.

    MCP tools in Copilot SDK are named as {server_name}-{tool_name}.
    This queries each server to discover its tools.

    Args:
        mcp_servers: MCP server config dict (server_name -> config).

    Returns:
        List of tool names in Copilot format ({server}-{tool}).
    """
    if not mcp_servers:
        return []

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        logger.warning("langchain-mcp-adapters not installed, cannot query MCP tools")
        return []

    # Build configs for MultiServerMCPClient
    configs = {}
    for server_name, server_config in mcp_servers.items():
        # Convert Copilot SDK format to langchain-mcp format
        if isinstance(server_config, dict):
            server_type = server_config.get("type", "local")
            if server_type in ("local", "stdio"):
                configs[server_name] = {
                    "transport": "stdio",
                    "command": server_config.get("command"),
                    "args": server_config.get("args", []),
                }
                if server_config.get("env"):
                    configs[server_name]["env"] = server_config["env"]
            elif server_type in ("http", "sse"):
                configs[server_name] = {
                    "transport": "sse",
                    "url": server_config.get("url"),
                }
        else:
            # TypedDict format
            command = getattr(server_config, "command", None) or server_config.get("command")
            if command:
                configs[server_name] = {
                    "transport": "stdio",
                    "command": command,
                    "args": getattr(server_config, "args", None) or server_config.get("args", []),
                }

    if not configs:
        return []

    try:
        import os
        import sys

        # Suppress MCP server startup messages
        try:
            stderr_fd = sys.stderr.fileno()
            saved_stderr = os.dup(stderr_fd)
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, stderr_fd)
            os.close(devnull)
            suppress_ok = True
        except (OSError, ValueError):
            suppress_ok = False

        try:
            # Query MCP servers for their tools
            client = MultiServerMCPClient(configs)
            tools = await client.get_tools()
        finally:
            if suppress_ok:
                os.dup2(saved_stderr, stderr_fd)
                os.close(saved_stderr)

        # Build Copilot-format tool names: {server}-{tool}
        # The tools come with server info we can use
        mcp_tool_names = []
        for tool in tools:
            # Tool names from MCP are just the tool name, we need to find the server
            # Try to match by checking which server has this tool
            tool_name = tool.name
            # Prefix with each server name that might have this tool
            for server_name in configs.keys():
                mcp_tool_names.append(f"{server_name}-{tool_name}")

        logger.info("Discovered %d MCP tools from %d servers: %s",
                   len(mcp_tool_names), len(configs), mcp_tool_names)
        return mcp_tool_names

    except Exception as e:
        logger.warning("Failed to query MCP tools: %s", e)
        return []

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
        self._mcp_servers: dict | None = None
        self._mcp_tool_names: list[str] | None = None  # Cached MCP tool names

    async def discover_mcp_tools(self, mcp_servers: dict | None) -> list[str]:
        """Discover MCP tools and cache them for session creation.

        Call this at startup to avoid delay on first message.

        Args:
            mcp_servers: MCP server config dict.

        Returns:
            List of discovered tool names.
        """
        if mcp_servers:
            self._mcp_tool_names = await _query_mcp_tool_names(mcp_servers)
            logger.info("Pre-cached %d MCP tool names", len(self._mcp_tool_names))
        else:
            self._mcp_tool_names = []
        return self._mcp_tool_names

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
                from copilot import SubprocessConfig
            except ImportError:
                raise ImportError(
                    "github-copilot-sdk is not installed. "
                    "Install it with: pip install github-copilot-sdk"
                )

            from clanker.copilot.auth import get_github_token, load_copilot_token

            token = get_github_token() or load_copilot_token()
            if not token:
                raise ValueError(
                    "No Copilot token found. Run '/gh-login' to authenticate."
                )

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
        mcp_servers: dict | None = None,
    ) -> Any:
        """Create a new Copilot session with persistence.

        Args:
            model: The model ID to use.
            tools: List of Copilot Tool objects.
            system_message: Optional system prompt.
            mcp_servers: MCP server configuration dict for native SDK support.

        Returns:
            The created session.
        """
        from copilot import PermissionHandler

        client = await self.ensure_client()

        self._session_id = f"clanker-{uuid.uuid4().hex[:8]}"
        self._current_model = model
        self._tools = tools

        # Build available_tools whitelist: our tools + MCP tools
        # This blocks ALL Copilot built-ins while allowing our tools and MCP tools
        available_tools: list[str] = []

        # Add our custom tool names
        if tools:
            available_tools.extend(t.name for t in tools)

        # Use cached MCP tool names if available, otherwise query dynamically
        if self._mcp_tool_names is not None:
            available_tools.extend(self._mcp_tool_names)
        elif mcp_servers:
            mcp_tool_names = await _query_mcp_tool_names(mcp_servers)
            self._mcp_tool_names = mcp_tool_names
            available_tools.extend(mcp_tool_names)

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
            "available_tools": available_tools,
        }

        if tools:
            session_kwargs["tools"] = tools
            logger.info("Creating session with %d custom tools + %d MCP tools",
                       len(tools), len(self._mcp_tool_names or []))

        if mcp_servers:
            session_kwargs["mcp_servers"] = mcp_servers
            logger.info("Creating session with %d MCP servers: %s", len(mcp_servers), list(mcp_servers.keys()))

        if system_message:
            session_kwargs["system_message"] = {
                "mode": "replace",
                "content": system_message,
            }

        self._session = await client.create_session(**session_kwargs)
        self._mcp_servers = mcp_servers
        logger.info("Created Copilot session: %s with model: %s", self._session_id, model)

        register_session(self._session_id, model)
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

        # Rebuild available_tools for resume
        available_tools: list[str] = []
        if tools:
            available_tools.extend(t.name for t in tools)
        elif self._tools:
            available_tools.extend(t.name for t in self._tools)

        # Use cached MCP tool names
        if self._mcp_tool_names:
            available_tools.extend(self._mcp_tool_names)

        resume_kwargs = {
            "on_permission_request": PermissionHandler.approve_all,
            "available_tools": available_tools,
        }

        if model:
            resume_kwargs["model"] = model
            self._current_model = model

        if tools:
            resume_kwargs["tools"] = tools
            self._tools = tools

        self._session = await client.resume_session(session_id, **resume_kwargs)
        logger.info("Resumed Copilot session: %s", session_id)
        return self._session

    async def get_or_create_session(
        self,
        model: str,
        tools: list | None = None,
        system_message: str | None = None,
        mcp_servers: dict | None = None,
    ) -> Any:
        """Get existing session or create a new one.

        Handles model switching and MCP server changes automatically.
        """
        if self._session is not None:
            # Check if MCP servers changed - need to recreate session
            mcp_changed = (mcp_servers is not None and self._mcp_servers != mcp_servers)
            if mcp_changed:
                logger.info("MCP servers changed, recreating session")
                return await self.new_session(model, tools, system_message, mcp_servers)

            # Check if we need to switch models
            if model != self._current_model:
                logger.info("Switching model from %s to %s", self._current_model, model)
                await self.resume_session(self._session_id, model, tools)

            return self._session

        return await self.create_session(model, tools, system_message, mcp_servers)

    async def new_session(
        self,
        model: str | None = None,
        tools: list | None = None,
        system_message: str | None = None,
        mcp_servers: dict | None = None,
    ) -> Any:
        """Start a fresh session (for /clear command)."""
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
            mcp_servers=mcp_servers,
        )

    async def list_sessions(self) -> list[dict]:
        """List all Copilot sessions from local registry."""
        return load_session_registry()

    async def delete_session(self, session_id: str) -> bool:
        """Delete a Copilot session."""
        client = await self.ensure_client()

        try:
            await client.delete_session(session_id)
            logger.info("Deleted session: %s", session_id)
        except Exception as e:
            logger.warning("Failed to delete session from SDK %s: %s", session_id, e)

        unregister_session(session_id)

        if session_id == self._session_id:
            self._session = None
            self._session_id = None

        return True

    async def send_message(self, prompt: str) -> Any:
        """Send a message to the current session."""
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
        self._mcp_servers = None
        logger.info("Copilot session manager cleaned up")
