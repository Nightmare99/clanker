"""Tests for system prompts."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_prompts_module():
    """Load prompts module directly without triggering agent imports."""
    module_path = Path("src/clanker/agent/prompts.py")
    spec = importlib.util.spec_from_file_location("clanker_prompts_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _get_system_prompt():
    return _load_prompts_module().SYSTEM_PROMPT


def _get_system_prompt_fn():
    return _load_prompts_module().get_system_prompt


class TestSystemPromptContent:
    """Tests for SYSTEM_PROMPT constant content."""

    def test_system_prompt_not_empty(self) -> None:
        """System prompt should have content."""
        SYSTEM_PROMPT = _get_system_prompt()
        assert len(SYSTEM_PROMPT) > 0

    def test_system_prompt_contains_core_principles(self) -> None:
        """System prompt should contain the 5 core principles."""
        SYSTEM_PROMPT = _get_system_prompt()
        assert "ACT, DON'T DISCUSS" in SYSTEM_PROMPT
        assert "UNDERSTAND BEFORE CHANGING" in SYSTEM_PROMPT
        assert "SURGICAL PRECISION" in SYSTEM_PROMPT
        assert "VERIFY YOUR WORK" in SYSTEM_PROMPT
        assert "THINK IN SYSTEMS" in SYSTEM_PROMPT

    def test_system_prompt_contains_tools_section(self) -> None:
        """System prompt should document available tools."""
        SYSTEM_PROMPT = _get_system_prompt()
        assert "# TOOLS" in SYSTEM_PROMPT
        assert "read_file" in SYSTEM_PROMPT
        assert "write_file" in SYSTEM_PROMPT
        assert "edit_file" in SYSTEM_PROMPT
        assert "execute_shell" in SYSTEM_PROMPT
        assert "glob_search" in SYSTEM_PROMPT
        assert "grep_search" in SYSTEM_PROMPT

    def test_system_prompt_mentions_project_instructions(self) -> None:
        """System prompt should mention reading project instructions."""
        SYSTEM_PROMPT = _get_system_prompt()
        assert "read_project_instructions" in SYSTEM_PROMPT
        assert "AGENTS.md" in SYSTEM_PROMPT

    def test_system_prompt_mentions_destructive_operations(self) -> None:
        """System prompt should warn about destructive operations."""
        SYSTEM_PROMPT = _get_system_prompt()
        assert "destructive" in SYSTEM_PROMPT.lower()
        assert "confirmation" in SYSTEM_PROMPT.lower()

    def test_system_prompt_mentions_memory_tools(self) -> None:
        """System prompt should document memory tools."""
        SYSTEM_PROMPT = _get_system_prompt()
        assert "remember" in SYSTEM_PROMPT
        assert "recall" in SYSTEM_PROMPT


class TestGetSystemPrompt:
    """Tests for get_system_prompt function."""

    def test_get_system_prompt_no_args(self) -> None:
        """get_system_prompt without args returns base prompt."""
        get_system_prompt = _get_system_prompt_fn()
        SYSTEM_PROMPT = _get_system_prompt()
        prompt = get_system_prompt()
        assert SYSTEM_PROMPT in prompt

    def test_get_system_prompt_with_working_directory(self) -> None:
        """get_system_prompt with working_directory adds environment section."""
        get_system_prompt = _get_system_prompt_fn()
        prompt = get_system_prompt(working_directory="/home/test/project")
        assert "# ENVIRONMENT" in prompt
        assert "/home/test/project" in prompt
        assert "Working directory:" in prompt

    def test_get_system_prompt_working_directory_includes_instruction(self) -> None:
        """Working directory prompt includes instruction to read project rules."""
        get_system_prompt = _get_system_prompt_fn()
        prompt = get_system_prompt(working_directory="/home/test/project")
        assert "read_project_instructions" in prompt

    def test_get_system_prompt_base_prompt_always_included(self) -> None:
        """Base SYSTEM_PROMPT is always included regardless of args."""
        get_system_prompt = _get_system_prompt_fn()
        prompt1 = get_system_prompt()
        prompt2 = get_system_prompt(working_directory="/path")
        prompt3 = get_system_prompt(working_directory="/path", user_query="test query")

        for prompt in [prompt1, prompt2, prompt3]:
            assert "ACT, DON'T DISCUSS" in prompt
            assert "SURGICAL PRECISION" in prompt


class TestPromptCodeQuality:
    """Tests for code quality guidelines in prompt."""

    def test_prompt_emphasizes_minimal_changes(self) -> None:
        """Prompt should emphasize minimal, targeted changes."""
        SYSTEM_PROMPT = _get_system_prompt()
        assert "minimal" in SYSTEM_PROMPT.lower()
        assert "targeted" in SYSTEM_PROMPT.lower()

    def test_prompt_emphasizes_reading_before_editing(self) -> None:
        """Prompt should emphasize reading files before editing."""
        SYSTEM_PROMPT = _get_system_prompt()
        assert "read" in SYSTEM_PROMPT.lower()
        assert "before" in SYSTEM_PROMPT.lower()

    def test_prompt_warns_against_unnecessary_abstraction(self) -> None:
        """Prompt should warn against premature abstraction."""
        SYSTEM_PROMPT = _get_system_prompt()
        assert "abstraction" in SYSTEM_PROMPT.lower() or "refactor" in SYSTEM_PROMPT.lower()

    def test_prompt_emphasizes_verification(self) -> None:
        """Prompt should emphasize testing and verification."""
        SYSTEM_PROMPT = _get_system_prompt()
        assert "test" in SYSTEM_PROMPT.lower()
        assert "verify" in SYSTEM_PROMPT.lower()


class TestPromptCommunicationGuidelines:
    """Tests for communication guidelines in prompt."""

    def test_prompt_emphasizes_conciseness(self) -> None:
        """Prompt should emphasize concise communication."""
        SYSTEM_PROMPT = _get_system_prompt()
        assert "concise" in SYSTEM_PROMPT.lower() or "brief" in SYSTEM_PROMPT.lower()

    def test_prompt_includes_good_example(self) -> None:
        """Prompt should include examples of good responses."""
        SYSTEM_PROMPT = _get_system_prompt()
        assert "Good:" in SYSTEM_PROMPT

    def test_prompt_includes_bad_example(self) -> None:
        """Prompt should include examples of bad responses."""
        SYSTEM_PROMPT = _get_system_prompt()
        assert "Bad:" in SYSTEM_PROMPT

    def test_prompt_discourages_asking_permission(self) -> None:
        """Prompt should discourage asking unnecessary permission."""
        SYSTEM_PROMPT = _get_system_prompt()
        assert "shall I" in SYSTEM_PROMPT or "should I" in SYSTEM_PROMPT
