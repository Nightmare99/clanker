"""Tests for ToolSettings configuration."""

from pathlib import Path

import pytest

from clanker.config.settings import Settings, ToolSettings


class TestToolSettingsDefaults:
    """Tests for ToolSettings default values."""

    def test_all_flags_default_to_true(self) -> None:
        ts = ToolSettings()
        assert ts.web_browsing is True
        assert ts.memory is True
        assert ts.skills is True
        assert ts.subagents is True
        assert ts.communication is True

    def test_individual_flag_override(self) -> None:
        ts = ToolSettings(web_browsing=False)
        assert ts.web_browsing is False
        assert ts.memory is True
        assert ts.skills is True
        assert ts.subagents is True
        assert ts.communication is True

    def test_all_flags_disabled(self) -> None:
        ts = ToolSettings(
            web_browsing=False,
            memory=False,
            skills=False,
            subagents=False,
            communication=False,
        )
        assert not any([
            ts.web_browsing,
            ts.memory,
            ts.skills,
            ts.subagents,
            ts.communication,
        ])


class TestToolSettingsInSettings:
    """Tests for ToolSettings nested inside Settings."""

    def test_settings_contains_tools(self) -> None:
        s = Settings()
        assert isinstance(s.tools, ToolSettings)
        assert s.tools.web_browsing is True

    def test_settings_from_yaml_with_tools(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
tools:
  web_browsing: false
  memory: false
  skills: true
  subagents: false
  communication: true
""")
        s = Settings.from_yaml(config_file)
        assert s.tools.web_browsing is False
        assert s.tools.memory is False
        assert s.tools.skills is True
        assert s.tools.subagents is False
        assert s.tools.communication is True

    def test_settings_save_yaml_round_trip(self, tmp_path: Path) -> None:
        s = Settings()
        s.tools.web_browsing = False
        s.tools.subagents = False
        config_file = tmp_path / "config.yaml"
        s.save_yaml(config_file)

        reloaded = Settings.from_yaml(config_file)
        assert reloaded.tools.web_browsing is False
        assert reloaded.tools.subagents is False
        assert reloaded.tools.memory is True
        assert reloaded.tools.skills is True
        assert reloaded.tools.communication is True

    def test_settings_from_yaml_partial_tools(self, tmp_path: Path) -> None:
        """Missing tool flags use defaults."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
tools:
  web_browsing: false
""")
        s = Settings.from_yaml(config_file)
        assert s.tools.web_browsing is False
        assert s.tools.memory is True  # default
        assert s.tools.skills is True  # default
        assert s.tools.subagents is True  # default
        assert s.tools.communication is True  # default

    def test_settings_from_yaml_no_tools_section(self, tmp_path: Path) -> None:
        """Missing tools section uses all defaults."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
agent:
  name: TestAgent
""")
        s = Settings.from_yaml(config_file)
        assert s.tools.web_browsing is True
        assert s.tools.memory is True
        assert s.tools.skills is True
        assert s.tools.subagents is True
        assert s.tools.communication is True

    def test_settings_model_dump_includes_tools(self) -> None:
        """model_dump includes tools section."""
        s = Settings()
        data = s.model_dump()
        assert "tools" in data
        assert data["tools"]["web_browsing"] is True
        assert data["tools"]["memory"] is True

    def test_settings_template_includes_tools(self, tmp_path: Path) -> None:
        """save_yaml_with_comments includes tools section."""
        template_file = tmp_path / "template.yaml"
        Settings().save_yaml_with_comments(template_file)
        content = template_file.read_text()
        assert "tools:" in content
        assert "web_browsing" in content
        assert "memory" in content
        assert "skills" in content
        assert "subagents" in content
        assert "communication" in content
