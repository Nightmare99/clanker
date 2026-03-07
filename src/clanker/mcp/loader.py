"""MCP server loader and manager."""

import os
import sys
from contextlib import contextmanager
from typing import Any

from langchain_core.tools import BaseTool

from clanker.config import Settings, get_settings
from clanker.logging import get_logger

# Module logger
logger = get_logger("mcp")


@contextmanager
def _suppress_stdio():
    """Suppress stdout/stderr from subprocesses (like MCP servers) at fd level."""
    try:
        # Save original file descriptors
        stdout_fd = sys.stdout.fileno()
        stderr_fd = sys.stderr.fileno()
        saved_stdout = os.dup(stdout_fd)
        saved_stderr = os.dup(stderr_fd)

        # Redirect to /dev/null
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, stdout_fd)
        os.dup2(devnull, stderr_fd)
        os.close(devnull)

        yield
    except (OSError, ValueError):
        # If we can't redirect (e.g., no real stdout/stderr), just continue
        yield
    else:
        # Restore original file descriptors
        os.dup2(saved_stdout, stdout_fd)
        os.dup2(saved_stderr, stderr_fd)
        os.close(saved_stdout)
        os.close(saved_stderr)


def build_mcp_server_configs(settings: Settings | None = None) -> dict[str, dict[str, Any]]:
    """Build MCP server configuration dict for MultiServerMCPClient.

    Args:
        settings: Optional settings override.

    Returns:
        Dict of server configs compatible with MultiServerMCPClient.
    """
    settings = settings or get_settings()

    if not settings.mcp.enabled:
        return {}

    configs = {}
    for name, server in settings.mcp.servers.items():
        if not server.enabled:
            continue

        if server.transport == "stdio":
            if not server.command:
                continue
            config: dict[str, Any] = {
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
        logger.debug("Configured MCP server: %s (%s)", name, server.transport)

    return configs


async def load_mcp_tools_async(settings: Settings | None = None) -> tuple[Any, list[BaseTool]]:
    """Load MCP tools asynchronously.

    This returns both the client (which must stay alive) and the tools.

    Args:
        settings: Optional settings override.

    Returns:
        Tuple of (client, tools). Client must be kept alive for tools to work.
    """
    configs = build_mcp_server_configs(settings)

    if not configs:
        return None, []

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        # Suppress MCP server startup messages
        with _suppress_stdio():
            client = MultiServerMCPClient(configs)
            tools = await client.get_tools()

        logger.info("Loaded %d MCP tools from %d servers", len(tools), len(configs))
        return client, tools

    except ImportError:
        raise ImportError(
            "langchain-mcp-adapters is required for MCP support. "
            "Install it with: pip install langchain-mcp-adapters"
        )
    except Exception as e:
        logger.warning("Failed to load MCP tools: %s", e)
        return None, []


# For backward compatibility - synchronous wrapper
def load_mcp_tools(settings: Settings | None = None) -> list[BaseTool]:
    """Synchronous wrapper to load MCP tools.

    Note: This is provided for backward compatibility but the async version
    is preferred as it properly manages the MCP client lifecycle.

    Args:
        settings: Optional settings override.

    Returns:
        List of tools from MCP servers.
    """
    import asyncio

    configs = build_mcp_server_configs(settings)
    if not configs:
        return []

    async def _load():
        from langchain_mcp_adapters.client import MultiServerMCPClient

        # Suppress MCP server startup messages
        with _suppress_stdio():
            client = MultiServerMCPClient(configs)
            tools = await client.get_tools()

        # Store client reference on tools to keep it alive
        for tool in tools:
            tool._mcp_client = client  # type: ignore
        return tools

    try:
        # Run in a fresh event loop in a separate thread to avoid anyio conflicts
        import concurrent.futures

        def run_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(_load())
            finally:
                loop.close()

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(run_in_thread)
            return future.result(timeout=60)

    except Exception as e:
        logger.warning("Failed to load MCP tools: %s", e)
        return []
