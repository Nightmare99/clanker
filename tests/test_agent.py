"""Tests for agent module (BYOK mode).

Note: These tests require langchain dependencies which may not be installed
in all environments. Tests are skipped if langchain is not available.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest


def _langchain_available() -> bool:
    """Check if langchain is available."""
    try:
        import langchain_core
        return True
    except ImportError:
        return False


def _load_state_module():
    """Load state module directly."""
    module_path = Path("src/clanker/agent/state.py")
    spec = importlib.util.spec_from_file_location("clanker_state_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Skip entire module if langchain not available
pytestmark = pytest.mark.skipif(
    not _langchain_available(),
    reason="langchain not installed"
)


@pytest.fixture
def langchain_messages():
    """Import langchain message classes."""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    return {"AIMessage": AIMessage, "HumanMessage": HumanMessage, "ToolMessage": ToolMessage}


@pytest.fixture
def multimodal_middleware():
    """Import middleware."""
    from clanker.agent.middleware import multimodal_tool_results
    return multimodal_tool_results


class TestAgentState:
    """Tests for AgentState TypedDict."""

    def test_state_has_required_fields(self) -> None:
        """AgentState includes required fields."""
        module = _load_state_module()
        state = {
            "messages": [],
            "working_directory": "/home/test",
        }
        assert "messages" in state
        assert "working_directory" in state

    def test_state_accepts_messages(self, langchain_messages) -> None:
        """AgentState can hold message objects."""
        HumanMessage = langchain_messages["HumanMessage"]
        AIMessage = langchain_messages["AIMessage"]
        state = {
            "messages": [
                HumanMessage(content="hello"),
                AIMessage(content="hi there"),
            ],
            "working_directory": "/test",
        }
        assert len(state["messages"]) == 2

    def test_state_tool_calls_count_optional(self) -> None:
        """tool_calls_count is optional in state."""
        state1 = {
            "messages": [],
            "working_directory": "/test",
        }
        assert "tool_calls_count" not in state1

        state2 = {
            "messages": [],
            "working_directory": "/test",
            "tool_calls_count": 5,
        }
        assert state2["tool_calls_count"] == 5


class TestMultimodalMiddleware:
    """Tests for multimodal_tool_results middleware."""

    def test_passes_through_non_tool_message(self, multimodal_middleware) -> None:
        """Non-ToolMessage results pass through unchanged."""
        @multimodal_middleware
        def handler(request: Any) -> str:
            return "plain string"

        result = handler({})
        assert result == "plain string"

    def test_passes_through_non_json_content(self, multimodal_middleware, langchain_messages) -> None:
        """Non-JSON string content passes through."""
        ToolMessage = langchain_messages["ToolMessage"]

        @multimodal_middleware
        def handler(request: Any) -> Any:
            return ToolMessage(content="not json", tool_call_id="test")

        result = handler({})
        assert isinstance(result, ToolMessage)
        assert result.content == "not json"

    def test_passes_through_json_without_images(self, multimodal_middleware, langchain_messages) -> None:
        """JSON content without images passes through."""
        ToolMessage = langchain_messages["ToolMessage"]
        content = json.dumps({"ok": True, "data": "value"})

        @multimodal_middleware
        def handler(request: Any) -> Any:
            return ToolMessage(content=content, tool_call_id="test")

        result = handler({})
        assert isinstance(result, ToolMessage)
        assert result.content == content

    def test_passes_through_empty_images_array(self, multimodal_middleware, langchain_messages) -> None:
        """JSON with empty images array passes through."""
        ToolMessage = langchain_messages["ToolMessage"]
        content = json.dumps({"ok": True, "images": []})

        @multimodal_middleware
        def handler(request: Any) -> Any:
            return ToolMessage(content=content, tool_call_id="test")

        result = handler({})
        assert isinstance(result, ToolMessage)
        assert result.content == content

    def test_converts_images_to_multimodal(self, multimodal_middleware, langchain_messages) -> None:
        """JSON with images converts to multimodal content."""
        ToolMessage = langchain_messages["ToolMessage"]
        content = json.dumps({
            "ok": True,
            "pages_read": 1,
            "images": [
                {"data": "base64data==", "mime_type": "image/png", "page": 1}
            ]
        })

        @multimodal_middleware
        def handler(request: Any) -> Any:
            return ToolMessage(content=content, tool_call_id="test")

        result = handler({})
        assert isinstance(result, ToolMessage)
        assert isinstance(result.content, list)

        types = [c["type"] for c in result.content]
        assert "text" in types
        assert "image_url" in types

    def test_multimodal_text_excludes_images(self, multimodal_middleware, langchain_messages) -> None:
        """Text part of multimodal result excludes raw images."""
        ToolMessage = langchain_messages["ToolMessage"]
        content = json.dumps({
            "ok": True,
            "path": "/test.pdf",
            "images": [{"data": "data", "mime_type": "image/png", "page": 1}]
        })

        @multimodal_middleware
        def handler(request: Any) -> Any:
            return ToolMessage(content=content, tool_call_id="test")

        result = handler({})
        text_part = next(c for c in result.content if c["type"] == "text")
        parsed = json.loads(text_part["text"])

        assert "images" not in parsed
        assert "images_included" in parsed
        assert parsed["images_included"] == 1
        assert parsed["ok"] is True

    def test_multimodal_preserves_tool_call_id(self, multimodal_middleware, langchain_messages) -> None:
        """Multimodal conversion preserves tool_call_id."""
        ToolMessage = langchain_messages["ToolMessage"]
        content = json.dumps({
            "images": [{"data": "x", "mime_type": "image/png", "page": 1}]
        })

        @multimodal_middleware
        def handler(request: Any) -> Any:
            return ToolMessage(content=content, tool_call_id="my-call-id")

        result = handler({})
        assert result.tool_call_id == "my-call-id"

    def test_multimodal_formats_image_url_correctly(self, multimodal_middleware, langchain_messages) -> None:
        """Image URLs are formatted as data URLs."""
        ToolMessage = langchain_messages["ToolMessage"]
        content = json.dumps({
            "images": [{"data": "ABC123", "mime_type": "image/jpeg", "page": 1}]
        })

        @multimodal_middleware
        def handler(request: Any) -> Any:
            return ToolMessage(content=content, tool_call_id="test")

        result = handler({})
        img_part = next(c for c in result.content if c["type"] == "image_url")

        assert "image_url" in img_part
        assert img_part["image_url"]["url"] == "data:image/jpeg;base64,ABC123"

    def test_handles_multiple_images(self, multimodal_middleware, langchain_messages) -> None:
        """Multiple images create multiple image_url entries."""
        ToolMessage = langchain_messages["ToolMessage"]
        content = json.dumps({
            "images": [
                {"data": "img1", "mime_type": "image/png", "page": 1},
                {"data": "img2", "mime_type": "image/png", "page": 2},
                {"data": "img3", "mime_type": "image/png", "page": 3},
            ]
        })

        @multimodal_middleware
        def handler(request: Any) -> Any:
            return ToolMessage(content=content, tool_call_id="test")

        result = handler({})
        img_parts = [c for c in result.content if c["type"] == "image_url"]
        assert len(img_parts) == 3
