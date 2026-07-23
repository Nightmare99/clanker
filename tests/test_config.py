"""Tests for configuration management."""

from pathlib import Path

import pytest

from clanker.config.settings import ContextSettings, OutputSettings, SafetySettings, Settings


class TestSettings:
    """Tests for Settings class."""

    def test_default_settings(self) -> None:
        """Test default settings are valid."""
        settings = Settings()

        assert settings.safety.require_confirmation is True
        assert settings.output.stream_responses is True
        assert settings.agent.name == "Clanker"

    def test_safety_settings_validation(self) -> None:
        """Test safety settings validation."""
        # Valid settings
        safety = SafetySettings(max_file_size=500_000)
        assert safety.max_file_size == 500_000

        # Invalid max_file_size (must be > 0)
        with pytest.raises(ValueError):
            SafetySettings(max_file_size=0)

    def test_output_settings_defaults(self) -> None:
        """Test output settings defaults."""
        output = OutputSettings()
        assert output.syntax_highlighting is True
        assert output.show_tool_calls is True
        assert output.stream_responses is True
        assert output.show_token_usage is True

    def test_context_settings_validation(self) -> None:
        """Test context settings validation."""
        # Valid settings
        ctx = ContextSettings(keep_recent_turns=6, summarization_threshold=70.0)
        assert ctx.keep_recent_turns == 6
        assert ctx.summarization_threshold == 70.0

        # Invalid threshold (too low)
        with pytest.raises(ValueError):
            ContextSettings(summarization_threshold=30.0)

        # Invalid threshold (too high)
        with pytest.raises(ValueError):
            ContextSettings(summarization_threshold=100.0)

    def test_max_agent_steps(self) -> None:
        """max_agent_steps defaults sensibly and validates bounds."""
        assert ContextSettings().max_agent_steps == 1000
        assert ContextSettings(max_agent_steps=2500).max_agent_steps == 2500
        # Below floor / above ceiling are rejected.
        with pytest.raises(ValueError):
            ContextSettings(max_agent_steps=5)
        with pytest.raises(ValueError):
            ContextSettings(max_agent_steps=20_000)

    def test_max_tool_call_arg_tokens(self, tmp_path: Path) -> None:
        """max_tool_call_arg_tokens defaults, validates, and round-trips."""
        # Default and validation (>= 0).
        assert ContextSettings().max_tool_call_arg_tokens == 4000
        assert ContextSettings(max_tool_call_arg_tokens=0).max_tool_call_arg_tokens == 0
        with pytest.raises(ValueError):
            ContextSettings(max_tool_call_arg_tokens=-1)

        # save_yaml / from_yaml round-trip.
        settings = Settings()
        settings.context.max_tool_call_arg_tokens = 1234
        config_file = tmp_path / "config.yaml"
        settings.save_yaml(config_file)
        reloaded = Settings.from_yaml(config_file)
        assert reloaded.context.max_tool_call_arg_tokens == 1234

        # Commented YAML template includes the key.
        template_file = tmp_path / "template.yaml"
        Settings().save_yaml_with_comments(template_file)
        assert "max_tool_call_arg_tokens" in template_file.read_text()

    def test_settings_from_yaml(self, tmp_path: Path) -> None:
        """Test loading settings from YAML."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
agent:
  name: TestAgent
safety:
  require_confirmation: false
output:
  show_tool_calls: false
""")

        settings = Settings.from_yaml(config_file)

        assert settings.agent.name == "TestAgent"
        assert settings.safety.require_confirmation is False
        assert settings.output.show_tool_calls is False

    def test_settings_save_yaml(self, tmp_path: Path) -> None:
        """Test saving settings to YAML."""
        config_file = tmp_path / "config.yaml"
        settings = Settings()

        settings.save_yaml(config_file)

        assert config_file.exists()
        content = config_file.read_text()
        assert "safety" in content
        assert "output" in content

    def test_settings_missing_file(self, tmp_path: Path) -> None:
        """Test loading from non-existent file returns defaults."""
        config_file = tmp_path / "nonexistent.yaml"

        settings = Settings.from_yaml(config_file, create_default=False)

        assert settings.safety.require_confirmation is True  # Default
