"""Tests for tool display behavior."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_tool_display_module():
    module_path = Path("src/clanker/ui/tool_display.py")
    spec = importlib.util.spec_from_file_location("clanker_tool_display_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_notify_tool_output_is_suppressed_in_generic_tool_display() -> None:
    module = _load_tool_display_module()
    ToolDisplayHandler = module.ToolDisplayHandler

    class FakeConsole:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, object]] = []

        def print_tool_use(self, tool_name: str, tool_input: dict) -> None:
            self.calls.append(("use", tool_name, tool_input))

        def print_tool_result(self, result: str, tool_name: str = "", tool_input=None) -> None:
            self.calls.append(("result", tool_name, result))

        def print_edit_diff(self, old_str: str, new_str: str) -> None:
            self.calls.append(("diff", old_str, new_str))

        def print_write_content(self, content: str, is_append: bool = False) -> None:
            self.calls.append(("write", content, is_append))

    starts: list[str] = []
    ends: list[str] = []
    console = FakeConsole()
    handler = ToolDisplayHandler(
        console=console,
        on_tool_start=lambda: starts.append("start"),
        on_tool_end=lambda: ends.append("end"),
    )

    handler.handle_tool_start("notify", {"message": "Scanning codebase...", "level": "info"})
    handler.handle_tool_end(
        "notify",
        '{"ok": true, "sent": true, "message": "Scanning codebase...", "level": "info"}',
    )

    assert starts == ["start"]
    assert ends == ["end"]
    assert console.calls == []
