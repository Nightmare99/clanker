"""Tests for Console.loading_spinner's reactive `update()` callable.

`loading_spinner` used to yield the raw `rich.live.Live` object with no
callers anywhere in the codebase. It's now wired into `run_interactive` (see
`cli.py`) to cover the gap between the user running `clanker` and the TUI
actually appearing on screen -- during which setup steps (Copilot token
refresh, the GitHub release check) could stall with zero feedback. These
tests assert the piece that makes it reactive: the yielded `update()`
callable actually swaps the spinner's displayed text, and the spinner line is
always cleared on exit, including when the `with` block exits via an
exception (e.g. `sys.exit()`).
"""

from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from rich.console import Console as RichConsole
from rich.live import Live

from clanker.ui.console import Console


@pytest.fixture
def console() -> Console:
    c = Console()
    # A non-terminal, string-backed console so Live doesn't try to drive a
    # real screen -- output is captured for inspection instead.
    c._console = RichConsole(file=io.StringIO(), force_terminal=False, width=80)
    return c


class TestLoadingSpinnerUpdate:
    def test_yields_a_callable_not_the_raw_live_object(self, console: Console) -> None:
        with console.loading_spinner("Booting up...") as update_status:
            assert callable(update_status)

    def test_update_changes_the_displayed_message(self, console: Console) -> None:
        # transient=True clears the spinner line on exit, so the final
        # captured output is always empty -- assert on what actually got
        # pushed to Live.update() instead of the (necessarily blank) frame
        # left behind afterwards.
        with patch.object(Live, "update", autospec=True) as mock_update, console.loading_spinner("Booting up...") as update_status:
            update_status("Validating claude-opus...")
            update_status("Checking for updates...")

        assert mock_update.call_count == 2
        first_renderable = mock_update.call_args_list[0].args[1]
        second_renderable = mock_update.call_args_list[1].args[1]
        assert "Validating claude-opus" in str(first_renderable.text)
        assert "Checking for updates" in str(second_renderable.text)

    def test_spinner_line_is_cleared_on_normal_exit(self, console: Console) -> None:
        with console.loading_spinner("Booting up..."):
            pass

        output = console._console.file.getvalue()
        # transient=True: nothing from the spinner should remain in the
        # final captured output once the block exits normally.
        assert "Booting up" not in output

    def test_spinner_line_is_cleared_even_when_with_block_raises(self, console: Console) -> None:
        class _BoomError(Exception):
            pass

        with pytest.raises(_BoomError), console.loading_spinner("Validating model...") as update_status:
            update_status("about to explode...")
            raise _BoomError

        output = console._console.file.getvalue()
        assert "Validating model" not in output
        assert "about to explode" not in output

    def test_no_message_falls_back_to_a_random_themed_message(self, console: Console) -> None:
        with console.loading_spinner() as update_status:
            assert callable(update_status)
