"""Tests for system prompts."""

from __future__ import annotations

import importlib.util
from pathlib import Path


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
        """System prompt should include memory tools marker or section."""
        SYSTEM_PROMPT = _get_system_prompt()
        # The raw prompt uses __MEMORY_TOOLS__ marker, resolved via get_system_prompt
        mod = _load_prompts_module()
        assert "__MEMORY_TOOLS__" in SYSTEM_PROMPT
        assert "remember" in mod.MEMORY_TOOLS_SECTION
        assert "recall" in mod.MEMORY_TOOLS_SECTION


class TestMemoryToolsSection:
    """The memory pitch should match the proactive framing given to other
    tools (notify, todo_write), not read as a passive afterthought."""

    def test_documents_all_four_memory_tools(self) -> None:
        section = _load_prompts_module().MEMORY_TOOLS_SECTION
        assert "remember" in section
        assert "recall" in section
        assert "forget" in section
        assert "list_memories" in section

    def test_has_proactive_framing_with_concrete_triggers(self) -> None:
        section = _load_prompts_module().MEMORY_TOOLS_SECTION
        assert "Proactively remember" in section
        # Concrete trigger examples, not just an abstract instruction.
        assert "convention" in section.lower()
        assert "preference" in section.lower()

    def test_mentions_automatic_injection(self) -> None:
        """The agent should know recall isn't the only path memories reach
        it, now that get_system_prompt can inject them automatically."""
        section = _load_prompts_module().MEMORY_TOOLS_SECTION
        assert "injected" in section.lower()


class TestGetSystemPrompt:
    """Tests for get_system_prompt function."""

    def test_get_system_prompt_no_args(self) -> None:
        """get_system_prompt without args returns base prompt with resolved markers."""
        get_system_prompt = _get_system_prompt_fn()
        prompt = get_system_prompt()
        # Core principles always present
        assert "ACT, DON'T DISCUSS" in prompt
        assert "SURGICAL PRECISION" in prompt
        # Markers are resolved (not present as raw markers)
        assert "__WEB_TOOLS__" not in prompt
        assert "__MEMORY_TOOLS__" not in prompt
        assert "__SKILLS_TOOLS__" not in prompt
        assert "__AGENTS_TOOLS__" not in prompt
        assert "__COMMUNICATION_TOOLS__" not in prompt

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


class TestSystemPromptMemoryInjection:
    """get_system_prompt's memory auto-injection (prompts.py:349-370) only
    runs when working_directory is passed -- these confirm it actually
    injects real memory content, not just that the code path is reachable."""

    def test_no_memories_yet_injects_nothing(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        get_system_prompt = _get_system_prompt_fn()
        prompt = get_system_prompt(working_directory=str(tmp_path))
        assert "Workspace context" not in prompt
        assert "Relevant Workspace Memories" not in prompt

    def test_recent_memories_injected_without_user_query(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        from clanker.memory.memories import get_memory_store

        store = get_memory_store(str(tmp_path))
        store.add("Uses pytest with asyncio_mode=auto", tags=["convention"])

        get_system_prompt = _get_system_prompt_fn()
        prompt = get_system_prompt(working_directory=str(tmp_path))
        assert "asyncio_mode=auto" in prompt

    def test_relevant_memories_injected_with_user_query(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        from clanker.memory.memories import get_memory_store

        store = get_memory_store(str(tmp_path))
        store.add("The auth handler lives in src/auth.py", tags=["architecture"])
        store.add("User prefers tabs over spaces", tags=["preference"])

        get_system_prompt = _get_system_prompt_fn()
        prompt = get_system_prompt(
            working_directory=str(tmp_path), user_query="where is the auth handler"
        )
        assert "src/auth.py" in prompt


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


def _get_load_user_instructions():
    return _load_prompts_module().load_user_instructions


class TestUserInstructions:
    """Tests for user instructions loaded from project and personal instructions.md."""

    def test_no_file_returns_empty(self, tmp_path, monkeypatch) -> None:
        """Returns empty string when instructions.md doesn't exist."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        load = _get_load_user_instructions()
        assert load(str(tmp_path)) == ""

    def test_reads_instructions_file(self, tmp_path, monkeypatch) -> None:
        """Reads content from .clanker/instructions.md."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        load = _get_load_user_instructions()
        clanker_dir = tmp_path / ".clanker"
        clanker_dir.mkdir()
        (clanker_dir / "instructions.md").write_text("Always respond in French.")
        assert load(str(tmp_path)) == "Always respond in French."

    def test_truncates_to_250_characters(self, tmp_path, monkeypatch) -> None:
        """Truncates instructions to first 250 characters."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        load = _get_load_user_instructions()
        clanker_dir = tmp_path / ".clanker"
        clanker_dir.mkdir()
        text = "a" * 400
        (clanker_dir / "instructions.md").write_text(text)
        result = load(str(tmp_path))
        assert len(result) == 250

    def test_under_250_chars_unchanged(self, tmp_path, monkeypatch) -> None:
        """Instructions under 250 characters are returned in full."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        load = _get_load_user_instructions()
        clanker_dir = tmp_path / ".clanker"
        clanker_dir.mkdir()
        text = "Short instruction set."
        (clanker_dir / "instructions.md").write_text(text)
        assert load(str(tmp_path)) == text

    def test_empty_file_returns_empty(self, tmp_path, monkeypatch) -> None:
        """Empty instructions file returns empty string."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        load = _get_load_user_instructions()
        clanker_dir = tmp_path / ".clanker"
        clanker_dir.mkdir()
        (clanker_dir / "instructions.md").write_text("   \n  \n  ")
        assert load(str(tmp_path)) == ""

    def test_reads_personal_instructions_file(self, tmp_path, monkeypatch) -> None:
        """Reads content from ~/.clanker/instructions.md when no project file exists."""
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        load = _get_load_user_instructions()
        personal_dir = home / ".clanker"
        personal_dir.mkdir(parents=True)
        (personal_dir / "instructions.md").write_text("Always respond in French.")
        assert load(str(tmp_path)) == "Always respond in French."

    def test_merges_personal_and_project(self, tmp_path, monkeypatch) -> None:
        """Both personal and project instructions are included, project last."""
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        load = _get_load_user_instructions()
        personal_dir = home / ".clanker"
        personal_dir.mkdir(parents=True)
        (personal_dir / "instructions.md").write_text("Always respond in French.")
        project_dir = tmp_path / ".clanker"
        project_dir.mkdir()
        (project_dir / "instructions.md").write_text("Always use TypeScript.")
        result = load(str(tmp_path))
        assert "Always respond in French." in result
        assert "Always use TypeScript." in result
        assert result.index("French") < result.index("TypeScript")

    def test_injected_into_system_prompt(self, tmp_path, monkeypatch) -> None:
        """User instructions appear in system prompt under USER INSTRUCTIONS."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        get_system_prompt = _get_system_prompt_fn()
        clanker_dir = tmp_path / ".clanker"
        clanker_dir.mkdir()
        (clanker_dir / "instructions.md").write_text("Always use TypeScript.")
        prompt = get_system_prompt(working_directory=str(tmp_path))
        assert "# USER INSTRUCTIONS" in prompt
        assert "Always use TypeScript." in prompt

    def test_not_injected_when_no_file(self, tmp_path, monkeypatch) -> None:
        """USER INSTRUCTIONS section absent when no instructions file."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        get_system_prompt = _get_system_prompt_fn()
        prompt = get_system_prompt(working_directory=str(tmp_path))
        assert "# USER INSTRUCTIONS" not in prompt
