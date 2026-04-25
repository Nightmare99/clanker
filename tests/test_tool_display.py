"""Tests for tool display behavior."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_tool_display_module():
    module_path = Path("src/clanker/ui/tool_display.py")
    spec = importlib.util.spec_from_file_location("clanker_tool_display_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeConsole:
    """Fake console for testing tool display."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._console = None  # For Live display compatibility

    def print_tool_use(self, tool_name: str, tool_input: dict) -> None:
        self.calls.append(("use", tool_name, tool_input))

    def print_tool_result(self, result: str, tool_name: str = "", tool_input=None) -> None:
        self.calls.append(("result", tool_name, result))

    def print_edit_diff(self, old_str: str, new_str: str) -> None:
        self.calls.append(("diff", old_str, new_str))

    def print_write_content(self, content: str, is_append: bool = False) -> None:
        self.calls.append(("write", content, is_append))

    def print_parallel_tools(self, tools: list) -> None:
        self.calls.append(("parallel", tools))


def test_notify_tool_output_is_suppressed_in_generic_tool_display() -> None:
    module = _load_tool_display_module()
    ToolDisplayHandler = module.ToolDisplayHandler

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


class TestToolDisplayHandler:
    """Tests for ToolDisplayHandler class."""

    def test_show_tool_returns_true_on_success(self) -> None:
        """show_tool returns True when tool is displayed."""
        module = _load_tool_display_module()
        handler = module.ToolDisplayHandler(console=FakeConsole())
        result = handler.show_tool("read_file", {"file_path": "/test.py"})
        assert result is True

    def test_show_tool_returns_false_when_disabled(self) -> None:
        """show_tool returns False when show_tool_calls is False."""
        module = _load_tool_display_module()
        handler = module.ToolDisplayHandler(console=FakeConsole(), show_tool_calls=False)
        result = handler.show_tool("read_file", {"file_path": "/test.py"})
        assert result is False

    def test_show_tool_detects_duplicate(self) -> None:
        """show_tool returns False for duplicate tool calls."""
        module = _load_tool_display_module()
        console = FakeConsole()
        handler = module.ToolDisplayHandler(console=console)

        # First call succeeds
        result1 = handler.show_tool("read_file", {"file_path": "/test.py"})
        # Second call with same input is duplicate
        result2 = handler.show_tool("read_file", {"file_path": "/test.py"})

        assert result1 is True
        assert result2 is False
        assert len(console.calls) == 1

    def test_show_tool_force_overrides_duplicate(self) -> None:
        """show_tool with force=True displays even duplicates."""
        module = _load_tool_display_module()
        console = FakeConsole()
        handler = module.ToolDisplayHandler(console=console)

        handler.show_tool("read_file", {"file_path": "/test.py"})
        handler.show_tool("read_file", {"file_path": "/test.py"}, force=True)

        assert len(console.calls) == 2

    def test_show_tool_skips_display_only_tools(self) -> None:
        """show_tool returns False for display-only tools like notify."""
        module = _load_tool_display_module()
        console = FakeConsole()
        handler = module.ToolDisplayHandler(console=console)

        result = handler.show_tool("notify", {"message": "test"})
        assert result is False
        assert len(console.calls) == 0

    def test_show_tool_prints_edit_diff(self) -> None:
        """show_tool prints diff for edit_file tool."""
        module = _load_tool_display_module()
        console = FakeConsole()
        handler = module.ToolDisplayHandler(console=console)

        handler.show_tool("edit_file", {
            "file_path": "/test.py",
            "old_string": "old",
            "new_string": "new",
        })

        call_types = [c[0] for c in console.calls]
        assert "use" in call_types
        assert "diff" in call_types

    def test_show_tool_prints_write_content(self) -> None:
        """show_tool prints content for write_file tool."""
        module = _load_tool_display_module()
        console = FakeConsole()
        handler = module.ToolDisplayHandler(console=console)

        handler.show_tool("write_file", {
            "file_path": "/test.py",
            "content": "print('hello')",
        })

        call_types = [c[0] for c in console.calls]
        assert "use" in call_types
        assert "write" in call_types


class TestToolResultDisplay:
    """Tests for show_tool_result."""

    def test_show_tool_result_returns_true(self) -> None:
        """show_tool_result returns True on success."""
        module = _load_tool_display_module()
        console = FakeConsole()
        handler = module.ToolDisplayHandler(console=console)

        result = handler.show_tool_result("read_file", '{"ok": true, "content": "test"}')
        assert result is True

    def test_show_tool_result_skips_empty(self) -> None:
        """show_tool_result skips empty results."""
        module = _load_tool_display_module()
        console = FakeConsole()
        handler = module.ToolDisplayHandler(console=console)

        handler.show_tool_result("read_file", "")
        handler.show_tool_result("read_file", "   ")

        # No result calls for empty content
        result_calls = [c for c in console.calls if c[0] == "result"]
        assert len(result_calls) == 0

    def test_show_tool_result_detects_duplicate(self) -> None:
        """show_tool_result skips duplicate results."""
        module = _load_tool_display_module()
        console = FakeConsole()
        handler = module.ToolDisplayHandler(console=console)

        handler.show_tool_result("read_file", '{"ok": true}')
        handler.show_tool_result("read_file", '{"ok": true}')

        result_calls = [c for c in console.calls if c[0] == "result"]
        assert len(result_calls) == 1


class TestToolQueue:
    """Tests for tool queuing for parallel display."""

    def test_queue_tool_adds_to_pending(self) -> None:
        """queue_tool adds tool to pending list."""
        module = _load_tool_display_module()
        handler = module.ToolDisplayHandler(console=FakeConsole())

        handler.queue_tool("read_file", {"file_path": "/a.py"})
        handler.queue_tool("read_file", {"file_path": "/b.py"})

        assert handler.has_pending_tools() is True

    def test_flush_pending_tools_displays_single(self) -> None:
        """flush_pending_tools displays single tool normally."""
        module = _load_tool_display_module()
        console = FakeConsole()
        handler = module.ToolDisplayHandler(console=console)

        handler.queue_tool("read_file", {"file_path": "/test.py"})
        handler.flush_pending_tools()

        assert handler.has_pending_tools() is False
        assert any(c[0] == "use" for c in console.calls)

    def test_flush_pending_tools_displays_multiple_as_parallel(self) -> None:
        """flush_pending_tools uses parallel display for multiple tools."""
        module = _load_tool_display_module()
        console = FakeConsole()
        handler = module.ToolDisplayHandler(console=console)

        handler.queue_tool("read_file", {"file_path": "/a.py"})
        handler.queue_tool("read_file", {"file_path": "/b.py"})
        handler.flush_pending_tools()

        assert any(c[0] == "parallel" for c in console.calls)

    def test_queue_tool_skips_already_shown(self) -> None:
        """queue_tool skips tools already shown."""
        module = _load_tool_display_module()
        handler = module.ToolDisplayHandler(console=FakeConsole())

        # Show tool first
        handler.show_tool("read_file", {"file_path": "/test.py"})
        # Queue same tool
        handler.queue_tool("read_file", {"file_path": "/test.py"})

        assert handler.has_pending_tools() is False


class TestClearToolTracking:
    """Tests for clear_tool_tracking."""

    def test_clear_all_tracking(self) -> None:
        """clear_tool_tracking(None) clears all tracking."""
        module = _load_tool_display_module()
        handler = module.ToolDisplayHandler(console=FakeConsole())

        handler.show_tool("read_file", {"file_path": "/a.py"})
        handler.show_tool("write_file", {"file_path": "/b.py", "content": "x"})
        handler.clear_tool_tracking()

        # Should be able to show same tools again
        result1 = handler.show_tool("read_file", {"file_path": "/a.py"})
        assert result1 is True

    def test_clear_specific_tool_tracking(self) -> None:
        """clear_tool_tracking(name) clears only that tool."""
        module = _load_tool_display_module()
        handler = module.ToolDisplayHandler(console=FakeConsole())

        handler.show_tool("read_file", {"file_path": "/a.py"})
        handler.show_tool("write_file", {"file_path": "/b.py", "content": "x"})
        handler.clear_tool_tracking("read_file")

        # read_file can show again
        result1 = handler.show_tool("read_file", {"file_path": "/a.py"})
        # write_file still blocked
        result2 = handler.show_tool("write_file", {"file_path": "/b.py", "content": "x"})

        assert result1 is True
        assert result2 is False


class TestCopilotCallback:
    """Tests for Copilot SDK callback integration."""

    def test_create_callback_returns_callable(self) -> None:
        """create_callback returns a function."""
        module = _load_tool_display_module()
        handler = module.ToolDisplayHandler(console=FakeConsole())
        callback = handler.create_callback()
        assert callable(callback)

    def test_callback_calls_handle_tool_start(self) -> None:
        """Callback with result=None calls handle_tool_start."""
        module = _load_tool_display_module()
        console = FakeConsole()
        starts = []
        handler = module.ToolDisplayHandler(
            console=console,
            on_tool_start=lambda: starts.append(1),
        )
        callback = handler.create_callback()

        callback("read_file", {"file_path": "/test.py"}, None)

        assert len(starts) == 1

    def test_callback_calls_handle_tool_end(self) -> None:
        """Callback with result calls handle_tool_end."""
        module = _load_tool_display_module()
        console = FakeConsole()
        ends = []
        handler = module.ToolDisplayHandler(
            console=console,
            on_tool_end=lambda: ends.append(1),
        )
        callback = handler.create_callback()

        # Must start first to have pending input
        callback("read_file", {"file_path": "/test.py"}, None)
        callback("read_file", {}, '{"ok": true}')

        assert len(ends) == 1


class TestNormalizeToolOutput:
    """Tests for normalize_tool_output function."""

    def test_normalize_none(self) -> None:
        """None returns empty string."""
        module = _load_tool_display_module()
        assert module.normalize_tool_output(None) == ""

    def test_normalize_string(self) -> None:
        """Plain string returns as-is."""
        module = _load_tool_display_module()
        assert module.normalize_tool_output("hello") == "hello"

    def test_normalize_list(self) -> None:
        """List items joined with newlines."""
        module = _load_tool_display_module()
        result = module.normalize_tool_output(["a", "b", "c"])
        assert result == "a\nb\nc"

    def test_normalize_dict_with_error(self) -> None:
        """Dict with error returns error message."""
        module = _load_tool_display_module()
        result = module.normalize_tool_output({"ok": False, "error": "file not found"})
        assert "Error:" in result
        assert "file not found" in result

    def test_normalize_dict_with_ok_preserves_json(self) -> None:
        """Dict with ok field preserves full JSON."""
        module = _load_tool_display_module()
        result = module.normalize_tool_output({"ok": True, "content": "data"})
        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert parsed["content"] == "data"

    def test_normalize_json_string(self) -> None:
        """JSON string dict is parsed and handled."""
        module = _load_tool_display_module()
        result = module.normalize_tool_output('{"ok": false, "error": "test error"}')
        assert "Error:" in result
        assert "test error" in result

    def test_normalize_text_result_for_llm_attribute(self) -> None:
        """Objects with text_result_for_llm are unwrapped."""
        module = _load_tool_display_module()

        class MockResult:
            text_result_for_llm = "extracted result"

        result = module.normalize_tool_output(MockResult())
        assert result == "extracted result"

    def test_normalize_langchain_message_content(self) -> None:
        """Objects with .content are unwrapped."""
        module = _load_tool_display_module()

        class MockMessage:
            content = "message content"

        result = module.normalize_tool_output(MockMessage())
        assert result == "message content"


class TestPendingToolCall:
    """Tests for PendingToolCall dataclass."""

    def test_pending_tool_call_fields(self) -> None:
        """PendingToolCall has expected fields."""
        module = _load_tool_display_module()
        call = module.PendingToolCall(
            tool_id="read_file:1",
            tool_name="read_file",
            tool_input={"file_path": "/test.py"},
        )
        assert call.tool_id == "read_file:1"
        assert call.tool_name == "read_file"
        assert call.tool_input["file_path"] == "/test.py"
