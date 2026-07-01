"""Tests for runtime state management."""

from __future__ import annotations

import importlib.util
from pathlib import Path


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
