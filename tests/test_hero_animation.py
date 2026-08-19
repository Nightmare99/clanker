"""Tests for the hero ascii-art animation: color wash loops forever, the
vertical bounce plays once and then settles flat (every letter level)."""

from __future__ import annotations

import colorsys
import math
import re

from clanker.ui.chat_log import _LIME_HUE, _LIME_PHASE_STEP, _HeroArt


def _make_hero() -> _HeroArt:
    hero = _HeroArt.__new__(_HeroArt)
    hero._art_lines = ["CLNKR"]
    hero._init_text = ""
    hero._is_final = True
    hero._model_info = "test-model"
    hero._yolo_mode = False
    hero._lime_phase = 0.0
    hero._wave_phase = 0.0
    hero._wave_settled = False
    hero._tick_timer = None
    hero._settle_timer = None
    hero.refresh = lambda *a, **k: None  # no live Textual app in these tests
    return hero


def test_lime_phase_keeps_advancing_after_settle() -> None:
    """The color wash must keep looping forever, even once the bounce is frozen."""
    hero = _make_hero()
    hero._settle()

    before = hero._lime_phase
    for _ in range(5):
        hero._tick()

    expected = (before + 5 * _LIME_PHASE_STEP) % 1.0
    assert math.isclose(hero._lime_phase, expected, rel_tol=1e-9)


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


def test_lime_shade_style_stays_within_lime_hue() -> None:
    """The wash must vary brightness only -- never drift into other hues
    (i.e. it's shades of lime, not a rainbow)."""
    hero = _make_hero()

    for tick in range(30):
        hero._lime_phase = (tick * 0.037) % 1.0
        for x in range(0, 40, 3):
            for y in range(0, 6):
                style = hero._lime_shade_style(x, y)
                r, g, b = (int(v) for v in re.match(r"rgb\((\d+),(\d+),(\d+)\)", style).groups())
                hue, _sat, _val = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                assert math.isclose(hue, _LIME_HUE, abs_tol=0.01)


def test_lime_shade_style_brightness_actually_varies() -> None:
    """Confirms the shimmer is live (not a flat, unchanging color) by checking
    brightness spans a real range across the grid at a fixed phase."""
    hero = _make_hero()
    hero._lime_phase = 0.4

    values = []
    for x in range(0, 60, 2):
        style = hero._lime_shade_style(x, 0)
        r, g, b = (int(v) for v in re.match(r"rgb\((\d+),(\d+),(\d+)\)", style).groups())
        _hue, _sat, val = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        values.append(val)

    assert max(values) - min(values) > 0.2


def test_set_final_only_schedules_settle_timer_once() -> None:
    hero = _make_hero()
    calls: list[tuple] = []
    hero.set_timer = lambda delay, callback: (calls.append((delay, callback)), "timer-obj")[1]

    hero.set_final("CLNKR", "model-a", False)
    hero.set_final("CLNKR", "model-a", False)
    hero.set_final("CLNKR", "model-a", False)

    assert len(calls) == 1
