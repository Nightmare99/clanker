"""Tests for prompt __MARKER__ resolution with tool flag combinations."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

from clanker.config.settings import Settings


def _load_prompts_module():
    """Load prompts module directly without triggering agent imports."""
    module_path = Path("src/clanker/agent/prompts.py")
    spec = importlib.util.spec_from_file_location("clanker_prompts_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _get_system_prompt_fn():
    return _load_prompts_module().get_system_prompt


def _mock_settings(**tool_flags):
    """Create a Settings instance with custom tool flags."""
    from clanker.config.settings import ToolSettings
    s = Settings()
    if tool_flags:
        s.tools = ToolSettings(**tool_flags)
    return s


class TestMarkersInRawPrompt:
    """Verify __MARKER__ placeholders exist in the raw SYSTEM_PROMPT."""

    def test_web_tools_marker_exists(self) -> None:
        mod = _load_prompts_module()
        assert "__WEB_TOOLS__" in mod.SYSTEM_PROMPT

    def test_communication_tools_marker_exists(self) -> None:
        mod = _load_prompts_module()
        assert "__COMMUNICATION_TOOLS__" in mod.SYSTEM_PROMPT

    def test_memory_tools_marker_exists(self) -> None:
        mod = _load_prompts_module()
        assert "__MEMORY_TOOLS__" in mod.SYSTEM_PROMPT

    def test_skills_tools_marker_exists(self) -> None:
        mod = _load_prompts_module()
        assert "__SKILLS_TOOLS__" in mod.SYSTEM_PROMPT

    def test_agents_tools_marker_exists(self) -> None:
        mod = _load_prompts_module()
        assert "__AGENTS_TOOLS__" in mod.SYSTEM_PROMPT


class TestMarkerResolutionEnabled:
    """When a flag is enabled, the marker is replaced with section content."""

    def test_web_tools_section_injected_when_enabled(self) -> None:
        get_system_prompt = _get_system_prompt_fn()
        settings = _mock_settings()
        with patch("clanker.config.get_settings", return_value=settings):
            prompt = get_system_prompt()
        assert "__WEB_TOOLS__" not in prompt
        assert "web_search" in prompt
        assert "web_read" in prompt

    def test_communication_section_injected_when_enabled(self) -> None:
        get_system_prompt = _get_system_prompt_fn()
        settings = _mock_settings()
        with patch("clanker.config.get_settings", return_value=settings):
            prompt = get_system_prompt()
        assert "__COMMUNICATION_TOOLS__" not in prompt
        assert "notify" in prompt
        assert "ask_user" in prompt

    def test_memory_section_injected_when_enabled(self) -> None:
        get_system_prompt = _get_system_prompt_fn()
        settings = _mock_settings()
        with patch("clanker.config.get_settings", return_value=settings):
            prompt = get_system_prompt()
        assert "__MEMORY_TOOLS__" not in prompt
        assert "remember" in prompt
        assert "recall" in prompt

    def test_skills_section_injected_when_enabled(self) -> None:
        get_system_prompt = _get_system_prompt_fn()
        settings = _mock_settings()
        with patch("clanker.config.get_settings", return_value=settings):
            prompt = get_system_prompt()
        assert "__SKILLS_TOOLS__" not in prompt
        assert "load_skill" in prompt

    def test_agents_section_injected_when_enabled(self) -> None:
        get_system_prompt = _get_system_prompt_fn()
        settings = _mock_settings()
        with patch("clanker.config.get_settings", return_value=settings):
            prompt = get_system_prompt()
        assert "__AGENTS_TOOLS__" not in prompt
        assert "load_agent" in prompt
        assert "spawn_subagent" in prompt


class TestMarkerResolutionDisabled:
    """When a flag is disabled, the marker is stripped from the prompt."""

    def test_web_tools_marker_stripped_when_disabled(self) -> None:
        get_system_prompt = _get_system_prompt_fn()
        settings = _mock_settings(web_browsing=False)
        with patch("clanker.config.get_settings", return_value=settings):
            prompt = get_system_prompt()
        assert "__WEB_TOOLS__" not in prompt
        assert "web_search" not in prompt
        assert "web_read" not in prompt

    def test_communication_marker_stripped_when_disabled(self) -> None:
        get_system_prompt = _get_system_prompt_fn()
        settings = _mock_settings(communication=False)
        with patch("clanker.config.get_settings", return_value=settings):
            prompt = get_system_prompt()
        assert "__COMMUNICATION_TOOLS__" not in prompt
        # "notify" and "ask_user" may appear elsewhere, but the section header won't
        assert "## Communication" not in prompt

    def test_memory_marker_stripped_when_disabled(self) -> None:
        get_system_prompt = _get_system_prompt_fn()
        settings = _mock_settings(memory=False)
        with patch("clanker.config.get_settings", return_value=settings):
            prompt = get_system_prompt()
        assert "__MEMORY_TOOLS__" not in prompt
        assert "## Memory" not in prompt

    def test_skills_marker_stripped_when_disabled(self) -> None:
        get_system_prompt = _get_system_prompt_fn()
        settings = _mock_settings(skills=False)
        with patch("clanker.config.get_settings", return_value=settings):
            prompt = get_system_prompt()
        assert "__SKILLS_TOOLS__" not in prompt
        assert "## Skills" not in prompt

    def test_agents_marker_stripped_when_disabled(self) -> None:
        get_system_prompt = _get_system_prompt_fn()
        settings = _mock_settings(subagents=False)
        with patch("clanker.config.get_settings", return_value=settings):
            prompt = get_system_prompt()
        assert "__AGENTS_TOOLS__" not in prompt
        assert "## Agents" not in prompt


class TestMarkerResolutionMixed:
    """Mixed flag combinations produce correct prompt."""

    def test_half_enabled_half_disabled(self) -> None:
        get_system_prompt = _get_system_prompt_fn()
        settings = _mock_settings(
            web_browsing=False,
            memory=False,
            skills=True,
            subagents=True,
            communication=False,
        )
        with patch("clanker.config.get_settings", return_value=settings):
            prompt = get_system_prompt()
        # Disabled: markers stripped, content absent
        assert "__WEB_TOOLS__" not in prompt
        assert "web_search" not in prompt
        assert "__MEMORY_TOOLS__" not in prompt
        assert "## Memory" not in prompt
        assert "__COMMUNICATION_TOOLS__" not in prompt
        assert "## Communication" not in prompt
        # Enabled: markers replaced with content
        assert "__SKILLS_TOOLS__" not in prompt
        assert "load_skill" in prompt
        assert "__AGENTS_TOOLS__" not in prompt
        assert "spawn_subagent" in prompt

    def test_all_disabled_strips_all_markers(self) -> None:
        get_system_prompt = _get_system_prompt_fn()
        settings = _mock_settings(
            web_browsing=False,
            memory=False,
            skills=False,
            subagents=False,
            communication=False,
        )
        with patch("clanker.config.get_settings", return_value=settings):
            prompt = get_system_prompt()
        assert "__WEB_TOOLS__" not in prompt
        assert "__COMMUNICATION_TOOLS__" not in prompt
        assert "__MEMORY_TOOLS__" not in prompt
        assert "__SKILLS_TOOLS__" not in prompt
        assert "__AGENTS_TOOLS__" not in prompt
        assert "web_search" not in prompt
        assert "## Memory" not in prompt
        assert "## Skills" not in prompt
        assert "## Agents" not in prompt
        assert "## Communication" not in prompt
        # Core prompt still intact
        assert "ACT, DON'T DISCUSS" in prompt
        assert "SURGICAL PRECISION" in prompt


class TestMarkerResolutionYamlIntegration:
    """Integration: YAML config drives prompt markers."""

    def test_yaml_flags_control_markers(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
tools:
  web_browsing: false
  memory: true
  skills: false
  subagents: false
  communication: true
""")
        settings = Settings.from_yaml(config_file)
        get_system_prompt = _get_system_prompt_fn()
        with patch("clanker.config.get_settings", return_value=settings):
            prompt = get_system_prompt()
        # Disabled
        assert "web_search" not in prompt
        assert "## Skills" not in prompt
        assert "## Agents" not in prompt
        # Enabled
        assert "## Memory" in prompt
        assert "## Communication" in prompt
