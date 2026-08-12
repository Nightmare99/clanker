"""Textual-level regression test: the hero widget must actually be measured
and laid out to fit its content, not clipped to a stale height.

This is the layout-engine counterpart to test_hero_animation.py's pure-logic
tests. Those tests can't catch a bug where the *pixels on screen* end up
truncated -- that only shows up once real Textual arrangement runs, which
is what this test exercises via a headless App.

Regression: refresh() without layout=True never re-measures a Static's auto
height. set_art()/set_final() go from empty initial content to multi-line
ascii art (and set_final adds trailing text lines on top), so skipping
layout there left the widget's height frozen at whatever it was before
content existed -- the art rendered but got clipped to ~0 visible rows.
"""

from __future__ import annotations

from textual.app import App, ComposeResult

from clanker.ui.chat_log import ChatLog

_ART = "AAA\nBBB\nCCC\nDDD\nEEE"  # 5 lines, mirrors the real multi-row CLNKR art


class _HeroHostApp(App):
    def compose(self) -> ComposeResult:
        yield ChatLog(id="chat-log")


async def test_hero_widget_height_matches_art_line_count() -> None:
    app = _HeroHostApp()
    async with app.run_test() as pilot:
        chat_log = app.query_one(ChatLog)
        chat_log.update_hero_art(_ART, init_text="  booting...")
        await pilot.pause()

        hero = chat_log._hero_widget
        assert hero is not None
        # 5 art lines + 1 blank separator + 1 init-text line = 7.
        assert hero.size.height >= 7, (
            f"hero widget height ({hero.size.height}) is smaller than its "
            f"content -- art is being clipped"
        )


async def test_hero_widget_height_grows_for_final_state() -> None:
    """set_final adds trailing text lines on top of the art -- height must grow to fit."""
    app = _HeroHostApp()
    async with app.run_test() as pilot:
        chat_log = app.query_one(ChatLog)
        chat_log.update_hero_art(_ART)
        await pilot.pause()
        height_during_boot = chat_log._hero_widget.size.height

        chat_log.update_hero_final(_ART, "test-model", yolo_mode=True)
        await pilot.pause()
        height_final = chat_log._hero_widget.size.height

        # Final state adds: blank, "Systems online" line, blank, model line,
        # blank, YOLO line, blank, blank, hint line -- strictly more lines
        # than the bare art-only boot state.
        assert height_final > height_during_boot


async def test_hero_widget_renders_all_art_lines_after_settle_tick() -> None:
    """A post-settle repaint tick must not shrink the widget back down."""
    app = _HeroHostApp()
    async with app.run_test() as pilot:
        chat_log = app.query_one(ChatLog)
        chat_log.update_hero_final(_ART, "test-model", yolo_mode=False)
        await pilot.pause()
        height_before = chat_log._hero_widget.size.height
        assert height_before >= len(_ART.split("\n"))

        # Force a settle + a couple of animation ticks, as the real timers would.
        hero = chat_log._hero_widget
        hero._settle()
        hero._tick()
        hero._tick()
        await pilot.pause()

        assert chat_log._hero_widget.size.height == height_before
