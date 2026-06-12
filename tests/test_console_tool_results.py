"""Tests for console tool result formatting."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


def _load_console_module():
    module_path = Path("src/clanker/ui/console.py")
    spec = importlib.util.spec_from_file_location("clanker_console_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_memory_save_result_prefers_message_over_raw_json() -> None:
    module = _load_console_module()
    Console = module.Console

    rendered: list[str] = []

    class DummyConsole:
        def print(self, value) -> None:
            rendered.append(str(value))

    dummy = SimpleNamespace()
    dummy._settings = SimpleNamespace(output=SimpleNamespace(show_tool_calls=True))
    dummy._console = DummyConsole()
    dummy._parse_tool_json = lambda result: json.loads(result)
    dummy._print_dim = lambda text: rendered.append(text)

    payload = json.dumps(
        {
            "ok": True,
            "message": "Stored in memory: # Plan Mode Implementation...",
            "memory_id": "3fa4f980",
            "tags": ["architecture", "plan-mode", "feature"],
        }
    )

    Console.print_tool_result(dummy, payload, tool_name="unknown", tool_input=None)

    assert rendered == ["Stored in memory: # Plan Mode Implementation..."]


def _make_dummy(rendered: list[str]):
    """Build a stand-in Console with the helpers print_tool_result depends on."""

    class DummyConsole:
        def print(self, value) -> None:
            rendered.append(str(value))

    dummy = SimpleNamespace()
    dummy._settings = SimpleNamespace(output=SimpleNamespace(show_tool_calls=True))
    dummy._console = DummyConsole()
    dummy._parse_tool_json = lambda result: (
        json.loads(result) if result.strip().startswith("{") else None
    )
    dummy._print_dim = lambda text: rendered.append(text)
    return dummy


def test_load_skill_result_shows_summary_not_raw_json() -> None:
    module = _load_console_module()
    Console = module.Console  # noqa: N806

    rendered: list[str] = []
    dummy = _make_dummy(rendered)

    payload = json.dumps(
        {
            "ok": True,
            "name": "frontend-design",
            "instructions": "# Frontend Design\n\nApproach this as the design lead...",
            "skill_directory": "/home/u/.clanker/skills/frontend-design",
            "note": "Follow these instructions...",
        }
    )

    Console.print_tool_result(
        dummy, payload, tool_name="load_skill", tool_input={"name": "frontend-design"}
    )

    blob = "\n".join(rendered)
    # The clean summary shows the name + directory...
    assert "Loaded skill" in blob
    assert "frontend-design" in blob
    assert "/home/u/.clanker/skills/frontend-design" in blob
    # ...and never dumps the raw instructions body or JSON keys.
    assert "Approach this as the design lead" not in blob
    assert "instructions" not in blob


def test_load_skill_error_shows_available() -> None:
    module = _load_console_module()
    Console = module.Console  # noqa: N806

    rendered: list[str] = []
    dummy = _make_dummy(rendered)

    payload = json.dumps(
        {"ok": False, "error": "Skill 'ghost' not found.", "available": ["a", "b"]}
    )

    Console.print_tool_result(dummy, payload, tool_name="load_skill", tool_input={"name": "ghost"})

    blob = "\n".join(rendered)
    assert "ghost" in blob
    assert "Available: a, b" in blob
