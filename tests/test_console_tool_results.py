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
