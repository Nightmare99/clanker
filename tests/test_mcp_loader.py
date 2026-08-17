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

from unittest.mock import MagicMock, patch

import pytest

from clanker.config.settings import MCPServerConfig, MCPSettings, Settings
from clanker.mcp import loader as mcp_loader


@pytest.fixture(autouse=True)
def _clear_cache_around_test():
    mcp_loader.clear_mcp_cache()
    yield
    mcp_loader.clear_mcp_cache()


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
