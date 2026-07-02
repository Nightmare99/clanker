"""Tests for token-usage tracking and the redesigned usage line.

Covers the config-only context window (no hardcoding), None-safe percentages,
and the themed `print_token_usage` rendering.
"""

from __future__ import annotations

from clanker.ui import token_tracking
from clanker.ui.token_tracking import SessionTokenTracker, TokenUsage


def _render_to_ansi(callback) -> str:
    """Render Console output with forced color to inspect marks and ANSI codes."""
    from rich.console import Console as RichConsole

    from clanker.ui.console import CLANKER_THEME, Console

    console = Console()
    console._console = RichConsole(
        theme=CLANKER_THEME, force_terminal=True, color_system="truecolor", width=120
    )
    with console._console.capture() as cap:
        callback(console)
    return cap.get()


class TestContextWindowSource:
    """The window is caller-supplied (from config), never hardcoded/guessed."""

    def test_no_hardcoded_mappings_remain(self) -> None:
        # The hardcoding stays gone — regression guard.
        assert not hasattr(token_tracking, "MODEL_CONTEXT_WINDOWS")
        assert not hasattr(token_tracking, "DEFAULT_CONTEXT_WINDOW")
        assert not hasattr(token_tracking, "get_context_window")

    def test_percent_with_window(self) -> None:
        t = SessionTokenTracker(context_window=200_000)
        t.add_turn(150_000, 1_000)
        assert t.context_used_percent is not None
        assert round(t.context_used_percent, 1) == 75.5
        assert round(t.context_remaining_percent, 1) == 24.5

    def test_none_window_gives_none(self) -> None:
        t = SessionTokenTracker(context_window=None)
        t.add_turn(272_840, 1_089)
        assert t.context_used_percent is None
        assert t.context_remaining_percent is None

    def test_zero_window_gives_none_no_divide_by_zero(self) -> None:
        t = SessionTokenTracker(context_window=0)
        t.add_turn(1_000, 100)
        assert t.context_used_percent is None

    def test_default_construction_is_none(self) -> None:
        # No window supplied at all → unknown, not a fabricated default.
        t = SessionTokenTracker()
        t.add_turn(1_000, 100)
        assert t.context_window is None
        assert t.context_used_percent is None

    def test_window_can_be_updated_between_turns(self) -> None:
        # Mirrors the /model live-refresh path in cli.py.
        t = SessionTokenTracker(context_window=None)
        t.add_turn(50_000, 500)
        assert t.context_used_percent is None
        t.context_window = 100_000
        t.add_turn(50_000, 500)
        assert round(t.context_used_percent, 1) == 50.5


class TestTokenUsageDataclass:
    """TokenUsage percentages are also None-safe."""

    def test_used_percent_with_window(self) -> None:
        u = TokenUsage(cumulative_total=64_000, context_window=128_000)
        assert u.context_used_percent == 50.0
        assert u.context_remaining_percent == 50.0
        assert u.context_remaining_tokens == 64_000

    def test_used_percent_without_window(self) -> None:
        u = TokenUsage(cumulative_total=64_000, context_window=None)
        assert u.context_used_percent is None
        assert u.context_remaining_percent is None
        assert u.context_remaining_tokens is None


class TestPrintTokenUsage:
    """The redesigned usage line: themed badge + None-aware context segment."""

    def test_badge_and_counts_present(self) -> None:
        out = _render_to_ansi(
            lambda c: c.print_token_usage(272_840, 1_089, 50.0)
        )
        # Muted dark mauve-pink pill background (rgb(80,38,62)).
        assert "48;2;80;38;62" in out
        assert "tokens" in out
        assert "in:272,840" in out
        assert "out:1,089" in out

    def test_percent_shown_when_window_known(self) -> None:
        out = _render_to_ansi(
            lambda c: c.print_token_usage(150_000, 1_000, 75.5)
        )
        # 24% remaining, rendered as a percentage + progress-bar gauge.
        assert "%" in out
        assert "24%" in out
        # The depleting fuel gauge draws filled + empty cells.
        assert "█" in out
        assert "░" in out

    def test_context_segment_omitted_when_none(self) -> None:
        out = _render_to_ansi(
            lambda c: c.print_token_usage(272_840, 1_089, None)
        )
        # Counts + badge still there...
        assert "in:272,840" in out
        assert "out:1,089" in out
        assert "48;2;80;38;62" in out
        # ...but no context percentage or progress-bar gauge.
        assert "%" not in out
        assert "█" not in out
        assert "░" not in out

    def test_cache_shown_only_when_present(self) -> None:
        with_cache = _render_to_ansi(
            lambda c: c.print_token_usage(1_000, 100, 10.0, cache_read=5_000)
        )
        assert "cache:5,000" in with_cache

        without_cache = _render_to_ansi(
            lambda c: c.print_token_usage(1_000, 100, 10.0, cache_read=0)
        )
        assert "cache:" not in without_cache

    def test_low_remaining_uses_red(self) -> None:
        # 95% used → 5% remaining → red (ANSI 31).
        out = _render_to_ansi(
            lambda c: c.print_token_usage(190_000, 500, 95.0)
        )
        assert "5%" in out
        assert "31m" in out

    def test_gauge_is_right_aligned(self) -> None:
        # The gauge is padded flush to the console's right edge: the last visible
        # cell is a bar glyph, and the plain-text line fills the full width.
        from rich.console import Console as RichConsole

        from clanker.ui.console import CLANKER_THEME, Console

        console = Console()
        # No color → the captured string is the visible text only (no ANSI),
        # so its length is the true cell width.
        console._console = RichConsole(
            theme=CLANKER_THEME, color_system=None, width=100
        )
        with console._console.capture() as cap:
            console.print_token_usage(150_000, 1_000, 40.0)
        line = cap.get().rstrip("\n")
        # Full-width line (right-aligned padding consumed the slack).
        assert len(line) == 100
        # Ends on a filled or empty gauge cell, not the token counts.
        assert line[-1] in "█░"

    def test_gauge_fill_scales_with_remaining(self) -> None:
        # More remaining → more filled cells. 90% remaining fills more of the
        # 16-cell bar than 10% remaining.
        high = _render_to_ansi(lambda c: c.print_token_usage(10_000, 100, 10.0))
        low = _render_to_ansi(lambda c: c.print_token_usage(180_000, 100, 90.0))
        assert high.count("█") > low.count("█")
