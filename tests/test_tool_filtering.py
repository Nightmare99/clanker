"""Tests for get_tools() filtering by settings.tools.* flags."""

from pathlib import Path
from unittest.mock import patch

from clanker.config.settings import Settings, ToolSettings
from clanker.tools import (
    ALL_TOOLS,
    ask_user,
    execute_shell,
    forget,
    get_tools,
    glob_search,
    grep_search,
    list_memories,
    load_agent,
    load_skill,
    notify,
    read_file,
    recall,
    remember,
    spawn_subagent,
    web_read,
    web_search,
    write_file,
)


def _mock_settings(**tool_flags) -> Settings:
    """Create a Settings instance with custom tools flags."""
    s = Settings()
    if tool_flags:
        s.tools = ToolSettings(**tool_flags)
    return s


class TestGetToolsAllEnabled:
    """When all flags are True, get_tools returns all tools."""

    def test_all_tools_returned_when_all_enabled(self) -> None:
        settings = _mock_settings()
        with patch("clanker.config.settings.get_settings", return_value=settings):
            tools = get_tools()
        assert len(tools) == len(ALL_TOOLS)
        assert [t.name for t in tools] == [t.name for t in ALL_TOOLS]


class TestGetToolsWebBrowsing:
    """web_browsing flag controls web_search and web_read."""

    def test_web_tools_excluded_when_disabled(self) -> None:
        settings = _mock_settings(web_browsing=False)
        with patch("clanker.config.settings.get_settings", return_value=settings):
            tools = get_tools()
        assert web_search not in tools
        assert web_read not in tools
        # Core tools still present
        assert read_file in tools
        assert execute_shell in tools

    def test_web_tools_included_when_enabled(self) -> None:
        settings = _mock_settings()
        with patch("clanker.config.settings.get_settings", return_value=settings):
            tools = get_tools()
        assert web_search in tools
        assert web_read in tools


class TestGetToolsMemory:
    """memory flag controls remember, recall, forget, list_memories."""

    def test_memory_tools_excluded_when_disabled(self) -> None:
        settings = _mock_settings(memory=False)
        with patch("clanker.config.settings.get_settings", return_value=settings):
            tools = get_tools()
        assert remember not in tools
        assert recall not in tools
        assert forget not in tools
        assert list_memories not in tools

    def test_memory_tools_included_when_enabled(self) -> None:
        settings = _mock_settings()
        with patch("clanker.config.settings.get_settings", return_value=settings):
            tools = get_tools()
        assert remember in tools
        assert recall in tools
        assert forget in tools
        assert list_memories in tools


class TestGetToolsSkills:
    """skills flag controls load_skill."""

    def test_skill_tool_excluded_when_disabled(self) -> None:
        settings = _mock_settings(skills=False)
        with patch("clanker.config.settings.get_settings", return_value=settings):
            tools = get_tools()
        assert load_skill not in tools

    def test_skill_tool_included_when_enabled(self) -> None:
        settings = _mock_settings()
        with patch("clanker.config.settings.get_settings", return_value=settings):
            tools = get_tools()
        assert load_skill in tools


class TestGetToolsSubagents:
    """subagents flag controls load_agent and spawn_subagent."""

    def test_subagent_tools_excluded_when_disabled(self) -> None:
        settings = _mock_settings(subagents=False)
        with patch("clanker.config.settings.get_settings", return_value=settings):
            tools = get_tools()
        assert load_agent not in tools
        assert spawn_subagent not in tools

    def test_subagent_tools_included_when_enabled(self) -> None:
        settings = _mock_settings()
        with patch("clanker.config.settings.get_settings", return_value=settings):
            tools = get_tools()
        assert load_agent in tools
        assert spawn_subagent in tools


class TestGetToolsCommunication:
    """communication flag controls notify and ask_user."""

    def test_communication_tools_excluded_when_disabled(self) -> None:
        settings = _mock_settings(communication=False)
        with patch("clanker.config.settings.get_settings", return_value=settings):
            tools = get_tools()
        assert notify not in tools
        assert ask_user not in tools

    def test_communication_tools_included_when_enabled(self) -> None:
        settings = _mock_settings()
        with patch("clanker.config.settings.get_settings", return_value=settings):
            tools = get_tools()
        assert notify in tools
        assert ask_user in tools


class TestGetToolsCoreAlwaysPresent:
    """Core tools are never filtered out."""

    def test_core_tools_always_present(self) -> None:
        settings = _mock_settings(
            web_browsing=False,
            memory=False,
            skills=False,
            subagents=False,
            communication=False,
        )
        with patch("clanker.config.settings.get_settings", return_value=settings):
            tools = get_tools()
        assert read_file in tools
        assert write_file in tools
        assert execute_shell in tools
        assert glob_search in tools
        assert grep_search in tools


class TestGetToolsMultipleCategoriesDisabled:
    """Disabling multiple categories removes all their tools."""

    def test_multiple_categories_disabled(self) -> None:
        settings = _mock_settings(
            web_browsing=False,
            memory=False,
            communication=False,
        )
        with patch("clanker.config.settings.get_settings", return_value=settings):
            tools = get_tools()
        # Excluded
        assert web_search not in tools
        assert web_read not in tools
        assert remember not in tools
        assert recall not in tools
        assert notify not in tools
        assert ask_user not in tools
        # Still present
        assert load_skill in tools
        assert load_agent in tools
        assert spawn_subagent in tools
        assert read_file in tools

    def test_all_categories_disabled_returns_only_core(self) -> None:
        settings = _mock_settings(
            web_browsing=False,
            memory=False,
            skills=False,
            subagents=False,
            communication=False,
        )
        with patch("clanker.config.settings.get_settings", return_value=settings):
            tools = get_tools()
        # No optional tools
        assert web_search not in tools
        assert web_read not in tools
        assert remember not in tools
        assert load_skill not in tools
        assert load_agent not in tools
        assert spawn_subagent not in tools
        assert notify not in tools
        assert ask_user not in tools
        # Core tools remain
        core_present = all(t in tools for t in [
            read_file, write_file, execute_shell, glob_search, grep_search,
        ])
        assert core_present


class TestGetToolsYamlIntegration:
    """Integration test: load settings from YAML and verify tool filtering."""

    def test_yaml_config_filters_tools(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
tools:
  web_browsing: false
  subagents: false
""")
        s = Settings.from_yaml(config_file)
        with patch("clanker.config.settings.get_settings", return_value=s):
            tools = get_tools()
        assert web_search not in tools
        assert web_read not in tools
        assert load_agent not in tools
        assert spawn_subagent not in tools
        # Enabled by default
        assert load_skill in tools
        assert notify in tools
