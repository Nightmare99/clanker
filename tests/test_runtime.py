"""Tests for runtime state management."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

import pytest


def _load_runtime_module():
    """Load runtime module directly without package import."""
    module_path = Path("src/clanker/runtime.py")
    spec = importlib.util.spec_from_file_location("clanker_runtime_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Load module once for use in tests
runtime = _load_runtime_module()


class TestYoloMode:
    """Tests for yolo mode functions."""

    def test_yolo_mode_default_false(self) -> None:
        """Yolo mode should be disabled by default."""
        runtime._yolo_mode = False
        assert runtime.is_yolo_mode() is False

    def test_set_yolo_mode_enables(self) -> None:
        """Setting yolo mode to True enables it."""
        runtime.set_yolo_mode(True)
        assert runtime.is_yolo_mode() is True
        runtime.set_yolo_mode(False)

    def test_set_yolo_mode_disables(self) -> None:
        """Setting yolo mode to False disables it."""
        runtime.set_yolo_mode(True)
        runtime.set_yolo_mode(False)
        assert runtime.is_yolo_mode() is False


class TestCopilotMode:
    """Tests for Copilot mode functions."""

    def test_copilot_mode_default_false(self) -> None:
        """Copilot mode should be disabled by default."""
        runtime._copilot_mode = False
        assert runtime.is_copilot_mode() is False

    def test_set_copilot_mode_enables(self) -> None:
        """Setting Copilot mode to True enables it."""
        runtime.set_copilot_mode(True)
        assert runtime.is_copilot_mode() is True
        runtime.set_copilot_mode(False)

    def test_set_copilot_mode_disables(self) -> None:
        """Setting Copilot mode to False disables it."""
        runtime.set_copilot_mode(True)
        runtime.set_copilot_mode(False)
        assert runtime.is_copilot_mode() is False


class TestParseModelSelection:
    """Tests for parse_model_selection function."""

    def test_simple_model_no_effort(self) -> None:
        """Simple model ID returns no reasoning effort."""
        model, effort = runtime.parse_model_selection("gpt-4.1")
        assert model == "gpt-4.1"
        assert effort is None

    def test_model_with_low_effort(self) -> None:
        """Model with (low) suffix extracts correctly."""
        model, effort = runtime.parse_model_selection("claude-sonnet-4 (low)")
        assert model == "claude-sonnet-4"
        assert effort == "low"

    def test_model_with_medium_effort(self) -> None:
        """Model with (medium) suffix extracts correctly."""
        model, effort = runtime.parse_model_selection("o3-mini (medium)")
        assert model == "o3-mini"
        assert effort == "medium"

    def test_model_with_high_effort(self) -> None:
        """Model with (high) suffix extracts correctly."""
        model, effort = runtime.parse_model_selection("claude-opus-4 (high)")
        assert model == "claude-opus-4"
        assert effort == "high"

    def test_model_with_xhigh_effort(self) -> None:
        """Model with (xhigh) suffix extracts correctly."""
        model, effort = runtime.parse_model_selection("o3 (xhigh)")
        assert model == "o3"
        assert effort == "xhigh"

    def test_model_with_invalid_effort_ignored(self) -> None:
        """Model with invalid effort suffix is not parsed as effort."""
        model, effort = runtime.parse_model_selection("model-name (invalid)")
        assert model == "model-name (invalid)"
        assert effort is None

    def test_model_with_whitespace(self) -> None:
        """Whitespace is trimmed properly."""
        model, effort = runtime.parse_model_selection("  gpt-4.1 (high)  ")
        assert model == "gpt-4.1"
        assert effort == "high"

    def test_model_with_parens_in_name_no_effort(self) -> None:
        """Model with parens not at end doesn't confuse parser."""
        model, effort = runtime.parse_model_selection("model-(v2)")
        assert model == "model-(v2)"
        assert effort is None


class TestFormatModelDisplay:
    """Tests for format_model_display function."""

    def test_model_without_effort(self) -> None:
        """Model without effort returns just the model."""
        result = runtime.format_model_display("gpt-4.1", None)
        assert result == "gpt-4.1"

    def test_model_with_effort(self) -> None:
        """Model with effort returns formatted string."""
        result = runtime.format_model_display("claude-sonnet-4", "high")
        assert result == "claude-sonnet-4 (high)"

    def test_roundtrip_parse_and_format(self) -> None:
        """Parsing then formatting returns original string."""
        original = "o3 (xhigh)"
        model, effort = runtime.parse_model_selection(original)
        result = runtime.format_model_display(model, effort)
        assert result == original


class TestCopilotModelConfig:
    """Tests for Copilot model configuration persistence."""

    @pytest.fixture
    def temp_config_path(self, tmp_path: Path):
        """Create a temporary config path and mock it."""
        config_file = tmp_path / "copilot_default_model.json"
        with mock.patch.object(runtime, "COPILOT_MODEL_PATH", config_file):
            # Reset global state
            runtime._copilot_model = None
            runtime._copilot_reasoning_effort = None
            yield config_file

    def test_load_default_when_no_file(self, temp_config_path: Path) -> None:
        """Returns default model when no config file exists."""
        model, effort = runtime._load_copilot_config()
        assert model == runtime.DEFAULT_COPILOT_MODEL
        assert effort is None

    def test_load_json_config(self, temp_config_path: Path) -> None:
        """Loads model and effort from JSON config."""
        temp_config_path.write_text('{"model": "claude-opus-4", "reasoning_effort": "high"}')
        model, effort = runtime._load_copilot_config()
        assert model == "claude-opus-4"
        assert effort == "high"

    def test_load_json_config_without_effort(self, temp_config_path: Path) -> None:
        """Loads model without effort from JSON config."""
        temp_config_path.write_text('{"model": "gpt-4.1"}')
        model, effort = runtime._load_copilot_config()
        assert model == "gpt-4.1"
        assert effort is None

    def test_save_config_creates_file(self, temp_config_path: Path) -> None:
        """Saving config creates the JSON file."""
        runtime._save_copilot_config("o3", "xhigh")
        assert temp_config_path.exists()
        data = json.loads(temp_config_path.read_text())
        assert data["model"] == "o3"
        assert data["reasoning_effort"] == "xhigh"

    def test_save_config_without_effort(self, temp_config_path: Path) -> None:
        """Saving config without effort omits the field."""
        runtime._save_copilot_config("gpt-4.1", None)
        data = json.loads(temp_config_path.read_text())
        assert data["model"] == "gpt-4.1"
        assert "reasoning_effort" not in data

    def test_set_and_get_copilot_model(self, temp_config_path: Path) -> None:
        """set_copilot_model persists and get_copilot_model retrieves."""
        runtime.set_copilot_model("claude-sonnet-4", "medium")

        # Reset globals to force reload
        runtime._copilot_model = None
        runtime._copilot_reasoning_effort = None

        assert runtime.get_copilot_model() == "claude-sonnet-4"
        assert runtime.get_copilot_reasoning_effort() == "medium"

    def test_get_copilot_model_caches(self, temp_config_path: Path) -> None:
        """get_copilot_model caches the value after first load."""
        temp_config_path.write_text('{"model": "model-a"}')
        runtime._copilot_model = None

        # First call loads from file
        assert runtime.get_copilot_model() == "model-a"

        # Modify file (should not affect cached value)
        temp_config_path.write_text('{"model": "model-b"}')
        assert runtime.get_copilot_model() == "model-a"

    def test_invalid_json_falls_back_to_default(self, temp_config_path: Path) -> None:
        """Invalid JSON falls back to default model."""
        temp_config_path.write_text("not valid json {{{")
        model, effort = runtime._load_copilot_config()
        assert model == runtime.DEFAULT_COPILOT_MODEL
        assert effort is None


class TestReasoningEffortLevels:
    """Tests for reasoning effort level constants."""

    def test_valid_levels(self) -> None:
        """All expected levels are present."""
        assert "low" in runtime.REASONING_EFFORT_LEVELS
        assert "medium" in runtime.REASONING_EFFORT_LEVELS
        assert "high" in runtime.REASONING_EFFORT_LEVELS
        assert "xhigh" in runtime.REASONING_EFFORT_LEVELS

    def test_level_count(self) -> None:
        """Exactly 4 reasoning effort levels."""
        assert len(runtime.REASONING_EFFORT_LEVELS) == 4
