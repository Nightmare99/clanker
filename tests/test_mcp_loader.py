"""Tests for MCP tool discovery caching.

Without caching, every call to load_mcp_tools_async/load_mcp_tools builds a
fresh MultiServerMCPClient and re-lists tools from every configured server --
for stdio servers, that's a subprocess spawned and killed just to refresh a
schema list that hasn't changed. Since create_agent_graph_async runs on every
agent turn, this was happening every turn, not just once per session. These
tests assert the fix: discovery is cached across calls with the same
resolved config, shared between the sync/async loaders, and invalidated when
the config actually changes or clear_mcp_cache() is called.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from clanker.config.settings import MCPServerConfig, MCPSettings, Settings
from clanker.mcp import loader as mcp_loader


@pytest.fixture(autouse=True)
def _clear_cache_around_test():
    mcp_loader.clear_mcp_cache()
    yield
    mcp_loader.clear_mcp_cache()


@pytest.fixture(autouse=True)
def _isolate_stdio_errlog_patch(tmp_path, monkeypatch):
    """Every real load_mcp_tools_async/load_mcp_tools call now runs
    _patch_mcp_stdio_errlog() -- including in the tests below, which only
    mock out MultiServerMCPClient. Point its log file at a tmp dir instead
    of the real ~/.clanker/logs, and undo the module-level monkeypatch of
    langchain_mcp_adapters.sessions.stdio_client afterwards so it doesn't
    leak into other test files."""
    import langchain_mcp_adapters.sessions as mcp_sessions

    original_stdio_client = mcp_sessions.stdio_client
    monkeypatch.setattr(mcp_loader, "DEFAULT_LOG_DIR", tmp_path)
    monkeypatch.setattr(mcp_loader, "_mcp_stderr_file", None)
    yield
    mcp_sessions.stdio_client = original_stdio_client


def _settings_with_server(name: str = "fs", command: str = "npx", args=None) -> Settings:
    s = Settings()
    s.mcp = MCPSettings(
        enabled=True,
        servers={
            name: MCPServerConfig(
                transport="stdio", command=command, args=args or ["some-mcp-server"]
            )
        },
    )
    return s


def _mock_client_class(tool_names: list[str]):
    """A fake MultiServerMCPClient class that records construction count."""
    construct_calls = {"n": 0}

    class _FakeClient:
        def __init__(self, configs):
            construct_calls["n"] += 1
            self.configs = configs

        async def get_tools(self):
            tools = []
            for name in tool_names:
                t = MagicMock()
                t.name = name
                tools.append(t)
            return tools

    return _FakeClient, construct_calls


class TestAsyncCaching:
    @pytest.mark.asyncio
    async def test_second_call_with_same_config_does_not_reconstruct_client(self) -> None:
        fake_client_cls, calls = _mock_client_class(["tool_a"])
        settings = _settings_with_server()

        with patch("langchain_mcp_adapters.client.MultiServerMCPClient", fake_client_cls):
            client1, tools1 = await mcp_loader.load_mcp_tools_async(settings)
            client2, tools2 = await mcp_loader.load_mcp_tools_async(settings)

        assert calls["n"] == 1  # only spawned/discovered once
        assert client1 is client2
        assert tools1 is tools2

    @pytest.mark.asyncio
    async def test_changed_config_invalidates_cache(self) -> None:
        fake_client_cls, calls = _mock_client_class(["tool_a"])
        settings_a = _settings_with_server(command="npx")
        settings_b = _settings_with_server(command="uvx")  # different resolved config

        with patch("langchain_mcp_adapters.client.MultiServerMCPClient", fake_client_cls):
            await mcp_loader.load_mcp_tools_async(settings_a)
            await mcp_loader.load_mcp_tools_async(settings_b)

        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_clear_mcp_cache_forces_reload(self) -> None:
        fake_client_cls, calls = _mock_client_class(["tool_a"])
        settings = _settings_with_server()

        with patch("langchain_mcp_adapters.client.MultiServerMCPClient", fake_client_cls):
            await mcp_loader.load_mcp_tools_async(settings)
            mcp_loader.clear_mcp_cache()
            await mcp_loader.load_mcp_tools_async(settings)

        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_no_servers_configured_returns_empty_without_caching(self) -> None:
        settings = Settings()  # mcp.servers empty by default
        client, tools = await mcp_loader.load_mcp_tools_async(settings)
        assert client is None
        assert tools == []


class TestSyncAndAsyncShareCache:
    @pytest.mark.asyncio
    async def test_async_load_then_sync_load_reuses_cache(self) -> None:
        fake_client_cls, calls = _mock_client_class(["tool_a"])
        settings = _settings_with_server()

        with patch("langchain_mcp_adapters.client.MultiServerMCPClient", fake_client_cls):
            await mcp_loader.load_mcp_tools_async(settings)
            tools = mcp_loader.load_mcp_tools(settings)

        assert calls["n"] == 1
        assert len(tools) == 1

    def test_sync_load_then_sync_load_reuses_cache(self) -> None:
        fake_client_cls, calls = _mock_client_class(["tool_a"])
        settings = _settings_with_server()

        with patch("langchain_mcp_adapters.client.MultiServerMCPClient", fake_client_cls):
            mcp_loader.load_mcp_tools(settings)
            mcp_loader.load_mcp_tools(settings)

        assert calls["n"] == 1


class TestGraphUsesSharedCache:
    """The real bug report: create_agent_graph_async runs every turn -- verify
    it no longer re-discovers MCP tools on each call.

    create_agent (tools=None branch) itself is mocked out here -- the graph's
    internals (real model profile, middleware construction, etc.) aren't
    what's under test; only that create_agent_graph_async's own MCP-loading
    step goes through the shared cache when called repeatedly.
    """

    @pytest.mark.asyncio
    async def test_create_agent_graph_async_reuses_mcp_tools_across_turns(self) -> None:
        from clanker.agent.graph import create_agent_graph_async

        fake_client_cls, calls = _mock_client_class(["tool_a"])
        settings = _settings_with_server()

        # Needs a `.profile` dict (not a bare MagicMock) -- RobustSummarizationMiddleware's
        # fraction-based trigger reads model.profile["max_input_tokens"] at construction.
        fake_model = MagicMock()
        fake_model.profile = {"max_input_tokens": 100_000}

        with patch("langchain_mcp_adapters.client.MultiServerMCPClient", fake_client_cls), \
             patch("clanker.agent.graph.create_model", return_value=fake_model), \
             patch("clanker.agent.graph.create_agent", return_value=MagicMock()):
            await create_agent_graph_async(settings, tools=None)
            await create_agent_graph_async(settings, tools=None)

        assert calls["n"] == 1


class TestStdioErrlogPatch:
    """The user-visible bug: a stdio MCP server's own stderr (startup
    banners, its own logging) defaults to the real sys.stderr and leaks
    through the terminal the TUI owns, flashing briefly on screen. These
    tests assert the fix: `_patch_mcp_stdio_errlog` redirects it to a log
    file instead, lazily (no file is created just from loading tools with
    a mocked client) and only once per process.
    """

    def test_patch_wraps_stdio_client_away_from_real_stderr(self, monkeypatch) -> None:
        import langchain_mcp_adapters.sessions as mcp_sessions
        import mcp.client.stdio as mcp_stdio

        calls: list[dict] = []

        def fake_stdio_client(*args, **kwargs):
            calls.append(kwargs)
            return "sentinel-context-manager"

        monkeypatch.setattr(mcp_stdio, "stdio_client", fake_stdio_client)
        monkeypatch.setattr(mcp_sessions, "stdio_client", fake_stdio_client)

        mcp_loader._patch_mcp_stdio_errlog()
        result = mcp_sessions.stdio_client("fake-server-params")

        assert result == "sentinel-context-manager"
        assert calls[0]["errlog"] is not sys.stderr
        assert calls[0]["errlog"] is mcp_loader._get_mcp_stderr_log()

    def test_patch_does_not_open_log_file_eagerly(self) -> None:
        """Patching alone (as happens on every load_mcp_tools* call) must
        not touch the filesystem -- only an actual stdio session spawn
        should, so tests and turns without a real MCP server never create
        ~/.clanker/logs as a side effect."""
        mcp_loader._patch_mcp_stdio_errlog()

        assert not (mcp_loader.DEFAULT_LOG_DIR / "mcp-servers.log").exists()

    def test_patch_is_a_noop_after_first_call(self) -> None:
        import langchain_mcp_adapters.sessions as mcp_sessions

        mcp_loader._patch_mcp_stdio_errlog()
        patched_once = mcp_sessions.stdio_client
        mcp_loader._patch_mcp_stdio_errlog()

        assert mcp_sessions.stdio_client is patched_once

    @pytest.mark.asyncio
    async def test_load_mcp_tools_async_does_not_create_log_file_for_mocked_client(
        self,
    ) -> None:
        fake_client_cls, _ = _mock_client_class(["tool_a"])
        settings = _settings_with_server()

        with patch("langchain_mcp_adapters.client.MultiServerMCPClient", fake_client_cls):
            await mcp_loader.load_mcp_tools_async(settings)

        assert not (mcp_loader.DEFAULT_LOG_DIR / "mcp-servers.log").exists()
