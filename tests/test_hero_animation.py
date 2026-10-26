"""Tests for the hero ascii-art animation: typewriter slide-in reveal
and continuous color gradient wash.
"""

from __future__ import annotations

import colorsys
import math
import re

from clanker.ui.app import _CLNKR_ART
from clanker.ui.chat_log import (
    _BLUE_HUE,
    _CYAN_HUE,
    _GRADIENT_PHASE_STEP,
    _HeroArt,
)


def _make_hero() -> _HeroArt:
    hero = _HeroArt()
    hero._art_lines = ["CLNKR"]
    hero._init_text = ""
    hero._is_final = True
    hero._model_info = "test-model"
    hero._yolo_mode = False
    hero._gradient_phase = 0.0
    hero._reveal_cols = None
    hero._tick_timer = None
    hero._settle_timer = None
    hero.refresh = lambda *a, **k: None  # no live Textual app in these tests
    return hero


def test_gradient_phase_keeps_advancing() -> None:
    """The color wash must keep looping forever."""
    hero = _make_hero()
    before = hero._gradient_phase
    for _ in range(5):
        hero._tick()

    expected = (before + 5 * _GRADIENT_PHASE_STEP) % 1.0
    assert math.isclose(hero._gradient_phase, expected, rel_tol=1e-9)


def test_typewriter_reveal_columns() -> None:
    """Typewriter reveal renders progressively across columns."""
    hero = _make_hero()
    art = "ABCDEFG"
    hero.set_art(art, reveal_cols=3)
    rendered = hero.render().plain
    # Only first 3 columns revealed
    assert "ABC" in rendered
    assert "DEFG" not in rendered

    # Reveal all columns
    hero.set_art(art, reveal_cols=7)
    rendered_all = hero.render().plain
    assert "ABCDEFG" in rendered_all


def test_set_final_reveals_full_art() -> None:
    """set_final clears reveal limit and shows full art with final status lines."""
    hero = _make_hero()
    art = "HELLO WORLD"
    hero.set_art(art, reveal_cols=4)
    hero.set_final(art, "model-a", False)

    rendered = hero.render().plain
    assert "HELLO WORLD" in rendered
    assert "Systems online" in rendered
    assert "model-a" in rendered


def test_gradient_style_stays_within_cyan_blue_range() -> None:
    """The gradient wash must stay strictly within cyan to blue hues."""
    hero = _make_hero()

    for tick in range(30):
        hero._gradient_phase = (tick * 0.037) % 1.0
        for x in range(0, 40, 3):
            for y in range(0, 6):
                style = hero._gradient_style(x, y)
                m = re.match(r"rgb\((\d+),(\d+),(\d+)\)", style)
                assert m is not None
                r, g, b = (int(v) for v in m.groups())
                hue, _sat, _val = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                assert _CYAN_HUE - 0.01 <= hue <= _BLUE_HUE + 0.01


def test_gradient_style_hue_actually_varies() -> None:
    """Confirms the gradient spans a real hue range across the grid."""
    hero = _make_hero()
    hero._gradient_phase = 0.4

    hues = []
    for x in range(0, 60, 2):
        style = hero._gradient_style(x, 0)
        m = re.match(r"rgb\((\d+),(\d+),(\d+)\)", style)
        assert m is not None
        r, g, b = (int(v) for v in m.groups())
        hue, _sat, _val = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        hues.append(hue)

    assert max(hues) - min(hues) > 0.1


def test_no_clipping_of_art_height() -> None:
    """Verify that all lines of art are preserved with no row clipping."""
    hero = _make_hero()
    hero.set_art(_CLNKR_ART)
    rendered = hero.render().plain
    lines = [line for line in rendered.split("\n") if line.strip()]
    expected_lines = [line for line in _CLNKR_ART.split("\n") if line.strip()]
    assert len(lines) == len(expected_lines)
