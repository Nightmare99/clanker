"""MCP server loader and manager."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from langchain_core.tools import BaseTool

from clanker.config import Settings, get_settings


class MCPManager:
    """Manage MCP server connections and tools."""

    def __init__(self, settings: Settings | None = None):
        """Initialize the MCP manager.

        Args:
            settings: Optional settings override.
        """
        self._settings = settings or get_settings()
        self._client = None
        self._tools: list[BaseTool] = []
        self._server_names: dict[str, str] = {}  # tool_name -> server_name mapping

    @property
    def is_enabled(self) -> bool:
        """Check if MCP is enabled and has servers configured."""
        mcp = self._settings.mcp
        if not mcp.enabled:
            return False
        return any(s.enabled for s in mcp.servers.values())

    def _build_server_configs(self) -> dict[str, dict[str, Any]]:
        """Build server configuration dict for MultiServerMCPClient."""
        configs = {}
        for name, server in self._settings.mcp.servers.items():
            if not server.enabled:
                continue

            if server.transport == "stdio":
                if not server.command:
                    continue
                config = {
                    "transport": "stdio",
                    "command": server.command,
                    "args": server.args,
                }
                if server.env:
                    config["env"] = server.env
            elif server.transport == "sse":
                if not server.url:
                    continue
                config = {
                    "transport": "sse",
                    "url": server.url,
                }
            else:
                continue

            configs[name] = config

        return configs

    async def load_tools(self) -> list[BaseTool]:
        """Load tools from all configured MCP servers.

        Returns:
            List of tools from MCP servers.
        """
        if not self.is_enabled:
            return []

        configs = self._build_server_configs()
        if not configs:
            return []

        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient

            self._client = MultiServerMCPClient(configs)
            self._tools = await self._client.get_tools()

            # Map tool names to server names for display
            for tool in self._tools:
                # Try to extract server name from tool name (format: server__tool)
                tool_name = tool.name
                for server_name in configs:
                    if tool_name.startswith(f"{server_name}__") or server_name in tool_name:
                        self._server_names[tool_name] = server_name
                        break
                else:
                    # If no match, use first server or "mcp"
                    self._server_names[tool_name] = list(configs.keys())[0] if configs else "mcp"

            return self._tools

        except ImportError:
            raise ImportError(
                "langchain-mcp-adapters is required for MCP support. "
                "Install it with: pip install langchain-mcp-adapters"
            )
        except Exception as e:
            # Log but don't crash if MCP fails to load
            raise RuntimeError(f"Failed to load MCP tools: {e}") from e

    def get_server_name(self, tool_name: str) -> str:
        """Get the server name for a tool.

        Args:
            tool_name: Name of the tool.

        Returns:
            Name of the server providing the tool.
        """
        return self._server_names.get(tool_name, "mcp")

    @property
    def tools(self) -> list[BaseTool]:
        """Get loaded MCP tools."""
        return self._tools

    async def close(self) -> None:
        """Close MCP client connections."""
        # The client handles cleanup automatically
        self._client = None
        self._tools = []
        self._server_names = {}


def load_mcp_tools(settings: Settings | None = None) -> list[BaseTool]:
    """Synchronous wrapper to load MCP tools.

    Args:
        settings: Optional settings override.

    Returns:
        List of tools from MCP servers.
    """
    import nest_asyncio

    # Allow nested event loops
    nest_asyncio.apply()

    manager = MCPManager(settings)
    if not manager.is_enabled:
        return []

    try:
        return asyncio.run(manager.load_tools())
    except Exception:
        # Return empty list if MCP loading fails (don't break the app)
        return []


def get_mcp_manager(settings: Settings | None = None) -> MCPManager:
    """Get an MCP manager instance.

    Args:
        settings: Optional settings override.

    Returns:
        MCPManager instance.
    """
    return MCPManager(settings)
