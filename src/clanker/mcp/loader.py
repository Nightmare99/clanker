"""MCP server loader and manager.

MCP tool *discovery* (listing what tools a server offers) is cached process-
wide: without this, every call to `load_mcp_tools_async`/`load_mcp_tools`
constructs a fresh `MultiServerMCPClient` and calls `get_tools()`, which opens
a new session per server just to list its tools -- for stdio servers, that's
a subprocess spawned and killed purely to re-fetch a schema list that never
changes within a session. Since `create_agent_graph_async` runs fresh on
*every agent turn* (see `graph.py`), that cost was being paid every turn, not
just once at startup.

This does NOT change how a tool is actually *invoked* -- that already opens
its own fresh session per call, by the installed `langchain-mcp-adapters`
version's own design (stateless, no persistent connection held by the
client). So caching the discovery step is free: there is no "stale dead
connection" risk, because no connection is being kept alive across turns in
the first place -- only the (static, config-derived) tool list is reused.

Every one of those sessions -- discovery and each individual tool call --
spawns a real subprocess for stdio servers. `mcp.client.stdio.stdio_client`
pipes the child's stdout (it's the JSON-RPC channel), but its `errlog`
parameter defaults to the real `sys.stderr`, and `langchain-mcp-adapters`
never overrides it. So anything a server writes to its own stderr (startup
banners, its own logging) goes straight to the real terminal the TUI has
taken over, visible as a brief flash. `_patch_mcp_stdio_errlog` redirects
that to a log file instead, once per process -- see its docstring.
"""

import hashlib
import json
import os
import sys
import threading
from contextlib import contextmanager
from typing import Any

from langchain_core.tools import BaseTool

from clanker.config import Settings, get_settings
from clanker.logging import DEFAULT_LOG_DIR, get_logger

# Module logger
logger = get_logger("mcp")

# Process-wide cache of the last successful MCP discovery, shared by both the
# sync and async loaders (and their many call sites -- every agent turn,
# every `/compact`, every subagent) so servers are only spawned once per
# session instead of once per call. Keyed by a hash of the resolved server
# configs so changing MCP settings mid-session (e.g. a settings reload)
# correctly invalidates it instead of silently serving a stale tool list.
_cache_lock = threading.Lock()
_cached_config_hash: str | None = None
_cached_client: Any = None
_cached_tools: list[BaseTool] = []

# Lazily-opened file that stdio MCP servers' stderr gets redirected to, in
# place of the real terminal -- see `_patch_mcp_stdio_errlog`.
_mcp_stderr_lock = threading.Lock()
_mcp_stderr_file: Any = None


def _get_mcp_stderr_log() -> Any:
    """Open (once, process-wide) the log file that stdio MCP servers'
    stderr gets redirected to. Kept separate from the main clanker.log so a
    noisy or crashing server can't spam the primary log."""
    global _mcp_stderr_file
    with _mcp_stderr_lock:
        if _mcp_stderr_file is None or _mcp_stderr_file.closed:
            DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
            _mcp_stderr_file = open(DEFAULT_LOG_DIR / "mcp-servers.log", "a", encoding="utf-8")
        return _mcp_stderr_file


def _patch_mcp_stdio_errlog() -> None:
    """Redirect stdio MCP servers' stderr to a log file instead of the real
    terminal.

    `mcp.client.stdio.stdio_client(server, errlog=sys.stderr)` defaults to
    the real `sys.stderr`, and `langchain_mcp_adapters._create_stdio_session`
    calls it without overriding that -- there's no config knob for it. Since
    a server's own stderr writes (startup banners, its own logging) would
    otherwise go straight to the terminal the TUI owns, this reassigns
    `langchain_mcp_adapters.sessions.stdio_client` (looked up from that
    module's globals at call time, so reassigning it here takes effect for
    every session opened afterwards) to a version bound to a log file
    instead. A no-op past the first call in a process, since after patching
    `mcp_sessions.stdio_client` is no longer the pristine function this
    checks for.

    This function is called unconditionally at the top of every real MCP
    load (see call sites below), including in tests that only mock out
    `MultiServerMCPClient` -- so the log file itself is opened lazily, on
    first actual use inside the wrapper, not here. Opening it eagerly would
    mean merely calling this function creates `~/.clanker/logs/` as a side
    effect, even when no stdio session is ever spawned for real.
    """
    try:
        import langchain_mcp_adapters.sessions as mcp_sessions
        from mcp.client.stdio import stdio_client as real_stdio_client
    except ImportError:
        return

    if mcp_sessions.stdio_client is not real_stdio_client:
        return

    def _stdio_client_to_log_file(*args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("errlog", _get_mcp_stderr_log())
        return real_stdio_client(*args, **kwargs)

    mcp_sessions.stdio_client = _stdio_client_to_log_file


def _hash_configs(configs: dict[str, dict[str, Any]]) -> str:
    """Stable hash of resolved server configs, used to invalidate the cache."""
    return hashlib.sha256(json.dumps(configs, sort_keys=True).encode()).hexdigest()


def clear_mcp_cache() -> None:
    """Drop the cached MCP client/tools so the next load reconnects from scratch."""
    global _cached_config_hash, _cached_client, _cached_tools
    with _cache_lock:
        _cached_config_hash = None
        _cached_client = None
        _cached_tools = []


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
    """Load MCP tools asynchronously, reusing the process-wide discovery cache.

    Args:
        settings: Optional settings override.

    Returns:
        Tuple of (client, tools). Cached across calls with the same server
        config -- see the module docstring for why re-discovering on every
        call (e.g. every agent turn) is unnecessary and wasteful.
    """
    global _cached_config_hash, _cached_client, _cached_tools

    configs = build_mcp_server_configs(settings)

    if not configs:
        return None, []

    config_hash = _hash_configs(configs)
    with _cache_lock:
        if _cached_client is not None and _cached_config_hash == config_hash:
            return _cached_client, _cached_tools

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        _patch_mcp_stdio_errlog()

        # Suppress MCP server startup messages
        with _suppress_stdio():
            client = MultiServerMCPClient(configs)
            tools = await client.get_tools()

        logger.info("Loaded %d MCP tools from %d servers", len(tools), len(configs))
        with _cache_lock:
            _cached_client, _cached_tools, _cached_config_hash = client, tools, config_hash
        return client, tools

    except ImportError as e:
        raise ImportError(
            "langchain-mcp-adapters is required for MCP support. "
            "Install it with: pip install langchain-mcp-adapters"
        ) from e
    except Exception as e:
        logger.warning("Failed to load MCP tools: %s", e)
        return None, []


# For backward compatibility - synchronous wrapper
def load_mcp_tools(settings: Settings | None = None) -> list[BaseTool]:
    """Synchronous wrapper to load MCP tools, sharing the same discovery cache
    as :func:`load_mcp_tools_async` (see the module docstring).

    Note: This is provided for backward compatibility but the async version
    is preferred as it properly manages the MCP client lifecycle.

    Args:
        settings: Optional settings override.

    Returns:
        List of tools from MCP servers.
    """
    import asyncio

    global _cached_config_hash, _cached_client, _cached_tools

    configs = build_mcp_server_configs(settings)
    if not configs:
        return []

    config_hash = _hash_configs(configs)
    with _cache_lock:
        if _cached_client is not None and _cached_config_hash == config_hash:
            return list(_cached_tools)

    _patch_mcp_stdio_errlog()

    async def _load():
        from langchain_mcp_adapters.client import MultiServerMCPClient

        # Suppress MCP server startup messages
        with _suppress_stdio():
            client = MultiServerMCPClient(configs)
            tools = await client.get_tools()

        # Store client reference on tools to keep it alive
        for tool in tools:
            tool._mcp_client = client  # type: ignore
        return client, tools

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
            client, tools = future.result(timeout=60)

        with _cache_lock:
            _cached_client, _cached_tools, _cached_config_hash = client, tools, config_hash
        return tools

    except Exception as e:
        logger.warning("Failed to load MCP tools: %s", e)
        return []
