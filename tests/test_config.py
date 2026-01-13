"""Tests for configuration management."""

from pathlib import Path

import pytest

from clanker.config.settings import ModelSettings, SafetySettings, Settings


class TestSettings:
    """Tests for Settings class."""

    def test_default_settings(self) -> None:
        """Test default settings are valid."""
        settings = Settings()

        assert settings.model.provider == "anthropic"
        assert settings.model.temperature >= 0
        assert settings.model.temperature <= 2
        assert settings.safety.require_confirmation is True
        assert settings.output.stream_responses is True

    def test_model_settings_validation(self) -> None:
        """Test model settings validation."""
        # Valid settings
        model = ModelSettings(temperature=0.5)
        assert model.temperature == 0.5

        # Invalid temperature (too high)
        with pytest.raises(ValueError):
            ModelSettings(temperature=3.0)

        # Invalid temperature (negative)
        with pytest.raises(ValueError):
            ModelSettings(temperature=-0.5)

    def test_safety_settings_validation(self) -> None:
        """Test safety settings validation."""
        # Valid settings
        safety = SafetySettings(max_file_size=500_000)
        assert safety.max_file_size == 500_000

        # Invalid max_file_size
        with pytest.raises(ValueError):
            SafetySettings(max_file_size=0)

    def test_settings_from_yaml(self, tmp_path: Path) -> None:
        """Test loading settings from YAML."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
model:
  provider: openai
  name: gpt-4o
  temperature: 0.5
safety:
  require_confirmation: false
""")

        settings = Settings.from_yaml(config_file)

        assert settings.model.provider == "openai"
        assert settings.model.name == "gpt-4o"
        assert settings.model.temperature == 0.5
        assert settings.safety.require_confirmation is False

    def test_settings_save_yaml(self, tmp_path: Path) -> None:
        """Test saving settings to YAML."""
        config_file = tmp_path / "config.yaml"
        settings = Settings()
        settings.model.name = "test-model"

        settings.save_yaml(config_file)

        assert config_file.exists()
        content = config_file.read_text()
        assert "test-model" in content
        # API keys should not be saved
        assert "api_key" not in content.lower()

    def test_settings_missing_file(self, tmp_path: Path) -> None:
        """Test loading from non-existent file returns defaults."""
        config_file = tmp_path / "nonexistent.yaml"

        settings = Settings.from_yaml(config_file)

        assert settings.model.provider == "anthropic"  # Default
