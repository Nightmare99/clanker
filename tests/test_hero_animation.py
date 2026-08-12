"""Tests for the hero ascii-art animation: color wash loops forever, the
vertical bounce plays once and then settles flat (every letter level)."""

from __future__ import annotations

import math

from clanker.ui.chat_log import _RAINBOW_PHASE_STEP, _HeroArt


def _make_hero() -> _HeroArt:
    hero = _HeroArt.__new__(_HeroArt)
    hero._art_lines = ["CLNKR"]
    hero._init_text = ""
    hero._is_final = True
    hero._model_info = "test-model"
    hero._yolo_mode = False
    hero._rainbow_phase = 0.0
    hero._wave_phase = 0.0
    hero._wave_settled = False
    hero._tick_timer = None
    hero._settle_timer = None
    hero.refresh = lambda *a, **k: None  # no live Textual app in these tests
    return hero


def test_rainbow_phase_keeps_advancing_after_settle() -> None:
    """The color wash must keep looping forever, even once the bounce is frozen."""
    hero = _make_hero()
    hero._settle()

    before = hero._rainbow_phase
    for _ in range(5):
        hero._tick()

    expected = (before + 5 * _RAINBOW_PHASE_STEP) % 1.0
    assert math.isclose(hero._rainbow_phase, expected, rel_tol=1e-9)


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


def test_set_final_only_schedules_settle_timer_once() -> None:
    hero = _make_hero()
    calls: list[tuple] = []
    hero.set_timer = lambda delay, callback: (calls.append((delay, callback)), "timer-obj")[1]

    hero.set_final("CLNKR", "model-a", False)
    hero.set_final("CLNKR", "model-a", False)
    hero.set_final("CLNKR", "model-a", False)

    assert len(calls) == 1
