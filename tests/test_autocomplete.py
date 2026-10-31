"""Tests for tab autocomplete, slash command completion, and filesystem path completion."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult

from clanker.ui.app import PromptInput
from clanker.ui.completion_menu import (
    CompletionMenu,
    complete_filepaths,
    find_common_prefix,
)


def test_find_common_prefix():
    assert find_common_prefix([]) == ""
    assert find_common_prefix(["hello"]) == "hello"
    assert find_common_prefix(["hello", "help", "helmet"]) == "hel"
    assert find_common_prefix(["/model", "/model-test"]) == "/model"
    assert find_common_prefix(["abc", "def"]) == ""


def test_complete_filepaths(tmp_path: Path):
    # Create test directory structure
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    (tmp_path / "src" / "utils.py").write_text("pass")
    (tmp_path / "README.md").write_text("# Test")
    (tmp_path / ".hidden").write_text("secret")

    # Complete root entries
    matches = complete_filepaths("R", root_dir=tmp_path)
    assert len(matches) == 1
    assert matches[0].value == "README.md"
    assert matches[0].is_dir is False

    # Complete directory
    dir_matches = complete_filepaths("sr", root_dir=tmp_path)
    assert len(dir_matches) == 1
    assert dir_matches[0].value == "src/"
    assert dir_matches[0].is_dir is True

    # Complete inside directory
    sub_matches = complete_filepaths("src/m", root_dir=tmp_path)
    assert len(sub_matches) == 1
    assert sub_matches[0].value == "src/main.py"

    # Hidden files only matched if leading dot typed
    no_hidden = complete_filepaths("", root_dir=tmp_path)
    assert not any(m.value.startswith(".hidden") for m in no_hidden)
    with_dot = complete_filepaths(".", root_dir=tmp_path)
    assert any(".hidden" in m.value for m in with_dot)


def test_completion_menu_slash_commands():
    commands = ["/help", "/history", "/model", "/reload", "/restore", "/resume"]
    menu = CompletionMenu(commands)

    # Empty match
    matches = menu.compute_matches("/unknown")
    assert matches == []

    # Command matches
    matches = menu.compute_matches("/re")
    displays = [m.display for m in matches]
    assert "/reload" in displays
    assert "/restore" in displays
    assert "/resume" in displays
    assert "/help" not in displays


def test_completion_menu_subcommands():
    commands = ["/model", "/effort", "/help"]
    menu = CompletionMenu(commands)

    def sub_completer(cmd: str, arg_prefix: str) -> list[str]:
        if cmd == "/model":
            return [m for m in ["gpt-4o", "claude-sonnet", "o3-mini"] if m.startswith(arg_prefix)]
        if cmd == "/effort":
            return [e for e in ["low", "medium", "high", "max"] if e.startswith(arg_prefix)]
        return []

    menu.set_subcommand_completer(sub_completer)

    # Subcommand argument completion for /model
    matches = menu.compute_matches("/model cl")
    assert len(matches) == 1
    assert matches[0].value == "/model claude-sonnet"
    assert matches[0].display == "claude-sonnet"

    # Subcommand argument completion for /effort
    matches = menu.compute_matches("/effort m")
    displays = [m.display for m in matches]
    assert "medium" in displays
    assert "max" in displays
    assert "low" not in displays


def test_completion_menu_navigation():
    commands = ["/clear", "/compact", "/config"]
    menu = CompletionMenu(commands)
    matches = menu.compute_matches("/c")
    menu.show(matches)

    assert menu.is_open is True
    assert menu.get_selected().display == "/clear"

    # Next item wraps
    menu.next_item()
    assert menu.get_selected().display == "/compact"

    menu.next_item()
    assert menu.get_selected().display == "/config"

    menu.next_item()
    assert menu.get_selected().display == "/clear"

    # Prev item wraps
    menu.prev_item()
    assert menu.get_selected().display == "/config"

    # Hide closes
    menu.hide()
    assert menu.is_open is False
    assert menu.get_selected() is None


class _AutocompleteHostApp(App):
    def compose(self) -> ComposeResult:
        menu = CompletionMenu(["/help", "/history", "/model", "/reload"])
        prompt = PromptInput(id="prompt-input")
        prompt.set_completion_menu(menu)
        yield menu
        yield prompt


async def test_prompt_input_tab_completion_scenarios():
    app = _AutocompleteHostApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        menu = app.query_one(CompletionMenu)

        # 1. Single match expands immediately with trailing space
        prompt.value = "/he"
        prompt.cursor_position = len(prompt.value)
        prompt._on_tab()
        assert prompt.value == "/help "

        # 2. When multiple matches are available, Tab cycles through them
        prompt.value = "/h"
        await pilot.pause()
        # Menu auto-opened with /help highlighted initially
        assert menu.is_open is True
        assert menu.get_selected().display == "/help"

        # Tab cycles to /history
        prompt.cursor_position = len(prompt.value)
        prompt._on_tab()
        assert menu.get_selected().display == "/history"

        # Shift+Tab reverses back to /help
        prompt._on_tab(reverse=True)
        assert menu.get_selected().display == "/help"

        # 5. Accepting completion
        prompt._accept_completion(menu.get_selected())
        assert prompt.value == "/help "
        assert menu.is_open is False



async def test_path_completion_in_prompt_input(tmp_path: Path):
    # Setup files in tmp_path
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "api.md").write_text("API docs")
    (tmp_path / "main.py").write_text("pass")

    app = _AutocompleteHostApp()
    async with app.run_test():
        prompt = app.query_one(PromptInput)
        menu = app.query_one(CompletionMenu)
        menu.set_working_dir(tmp_path)

        # Type "@doc"
        prompt.value = "Inspect @doc"
        prompt.cursor_position = len(prompt.value)
        prompt._on_tab()

        # Should complete to @docs/ without space so user can continue typing sub-paths
        assert prompt.value == "Inspect @docs/"

        # Now type "a" -> "Inspect @docs/a"
        prompt.value = "Inspect @docs/a"
        prompt.cursor_position = len(prompt.value)
        prompt._on_tab()

        # Should complete to @docs/api.md with trailing space
        assert prompt.value == "Inspect @docs/api.md "


async def test_subcommand_common_prefix_expansion():
    app = _AutocompleteHostApp()
    async with app.run_test():
        prompt = app.query_one(PromptInput)
        menu = app.query_one(CompletionMenu)

        menu.set_subcommand_completer(
            lambda cmd, prefix: [m for m in ["claude-3-opus", "claude-3-sonnet", "gpt-4o"] if m.startswith(prefix)]
        )

        prompt.value = "/model c"
        prompt.cursor_position = len(prompt.value)
        prompt._on_tab()

        # Common prefix of claude-3-opus and claude-3-sonnet is claude-3-
        assert prompt.value == "/model claude-3-"
        assert menu.is_open is True
        assert len(menu._matches) == 2


async def test_completion_menu_positioned_above_input_area():
    app = _AutocompleteHostApp()
    async with app.run_test(size=(100, 30)) as pilot:
        prompt = app.query_one(PromptInput)
        menu = app.query_one(CompletionMenu)

        prompt.value = "/m"
        await pilot.pause()
        assert menu.is_open is True

        content_lines = min(len(menu._matches), 8)
        menu_height = content_lines + 2
        menu_bottom = menu.offset.y + menu_height
        prompt_top = prompt.region.y
        if prompt_top > 0:
            assert menu_bottom <= prompt_top
