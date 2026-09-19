"""Tests for the hero ascii-art animation: color wash loops forever, the
vertical bounce plays once and then settles flat (every letter level)."""

from __future__ import annotations

import colorsys
import math
import re

from clanker.ui.chat_log import (
    _BLUE_HUE,
    _CYAN_HUE,
    _GRADIENT_PHASE_STEP,
    _HeroArt,
)


def _make_hero() -> _HeroArt:
    hero = _HeroArt.__new__(_HeroArt)
    hero._art_lines = ["CLNKR"]
    hero._init_text = ""
    hero._is_final = True
    hero._model_info = "test-model"
    hero._yolo_mode = False
    hero._gradient_phase = 0.0
    hero._wave_phase = 0.0
    hero._wave_settled = False
    hero._tick_timer = None
    hero._settle_timer = None
    hero.refresh = lambda *a, **k: None  # no live Textual app in these tests
    return hero


def test_gradient_phase_keeps_advancing_after_settle() -> None:
    """The color wash must keep looping forever, even once the bounce is frozen."""
    hero = _make_hero()
    hero._settle()

    before = hero._gradient_phase
    for _ in range(5):
        hero._tick()

    expected = (before + 5 * _GRADIENT_PHASE_STEP) % 1.0
    assert math.isclose(hero._gradient_phase, expected, rel_tol=1e-9)


def test_wave_phase_frozen_after_settle() -> None:
    hero = _make_hero()
    hero._tick()
    hero._tick()
    assert hero._wave_phase != 0.0  # sanity: it was actually animating

    hero._settle()
    frozen_phase = hero._wave_phase

    for _ in range(5):
        hero._tick()

    assert hero._wave_phase == frozen_phase  # never advances again


def test_wave_offset_is_level_for_every_column_after_settle() -> None:
    hero = _make_hero()
    hero._tick()
    hero._tick()
    hero._tick()  # give it some non-trivial phase first

    hero._settle()

    for x in range(0, 50, 5):
        assert hero._wave_offset(x) == 0


def test_wave_offset_varies_before_settle() -> None:
    hero = _make_hero()
    hero._wave_phase = 1.2  # some arbitrary non-zero phase

    offsets = {hero._wave_offset(x) for x in (0, 10, 20, 30, 40)}
    # Not asserting exact values (that's the existing bounce math), just that
    # settling is what flattens it -- pre-settle, letters can differ from 0.
    assert offsets != {0}


def test_gradient_style_stays_within_cyan_blue_range() -> None:
    """The gradient wash must stay strictly within cyan to blue hues --
    never drift into green or magenta/red."""
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
    """Confirms the gradient is live (not a flat, unchanging color) by checking
    hue spans a real range between cyan and blue across the grid at a fixed phase."""
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


def test_set_final_only_schedules_settle_timer_once() -> None:
    hero = _make_hero()
    calls: list[tuple] = []
    hero.set_timer = lambda delay, callback: (calls.append((delay, callback)), "timer-obj")[1]

    hero.set_final("CLNKR", "model-a", False)
    hero.set_final("CLNKR", "model-a", False)
    hero.set_final("CLNKR", "model-a", False)

    assert len(calls) == 1
