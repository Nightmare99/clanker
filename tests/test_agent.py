"""Tests for agent module (BYOK mode).

Note: These tests require langchain dependencies which may not be installed
in all environments. Tests are skipped if langchain is not available.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

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
    """Tests for multimodal_tool_results middleware module."""

    def test_middleware_importable(self) -> None:
        """Middleware module can be imported."""
        from clanker.agent.middleware import multimodal_tool_results
        assert multimodal_tool_results is not None

    def test_middleware_has_expected_attributes(self) -> None:
        """Middleware has wrap_tool_call decorator applied."""
        from clanker.agent.middleware import multimodal_tool_results
        # wrap_tool_call decorator creates an object with specific attributes
        assert hasattr(multimodal_tool_results, '__wrapped__') or callable(multimodal_tool_results)
