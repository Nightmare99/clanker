"""Tests for theme configuration, API endpoints, and TUI integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from clanker.config.theme import (
    DEFAULT_ASCII_ART,
    MINIMAL_ASCII_ART,
    ROBOT_ASCII_ART,
    THEME_PRESETS,
    ColorPalette,
    HeroTheme,
    UIThemeConfig,
    generate_tcss,
    get_theme_config,
    hex_to_rgb,
    interpolate_color,
    reset_theme_config,
    rgb_str,
    rgb_to_hex,
    save_theme_config,
)
from clanker.config.web.app import create_app
from clanker.ui.chat_log import _HeroArt


@pytest.fixture(autouse=True)
def isolate_theme(tmp_path: Path):
    test_theme = tmp_path / "theme.yaml"
    with patch("clanker.config.theme.THEME_CONFIG_PATH", test_theme):
        yield


def test_hex_to_rgb_and_rgb_to_hex() -> None:
    assert hex_to_rgb("#00f0f0") == (0, 240, 240)
    assert hex_to_rgb("#fff") == (255, 255, 255)
    assert hex_to_rgb("rgb(10, 20, 30)") == (10, 20, 30)
    assert hex_to_rgb("invalid") == (0, 240, 240)  # fallback

    assert rgb_to_hex(0, 240, 240) == "#00f0f0"
    assert rgb_to_hex(255, 255, 255) == "#ffffff"
    assert rgb_to_hex(-10, 300, 100) == "#00ff64"  # clamped

    assert rgb_str("#00f0f0") == "rgb(0,240,240)"


def test_interpolate_color() -> None:
    # 0.0 factor should equal start color
    assert interpolate_color("#000000", "#ffffff", 0.0) == "#000000"
    # 1.0 factor should equal end color
    assert interpolate_color("#000000", "#ffffff", 1.0) == "#ffffff"
    # 0.5 factor should be middle gray
    mid = interpolate_color("#000000", "#ffffff", 0.5)
    assert mid in ("#7f7f7f", "#808080")


def test_theme_presets_structure() -> None:
    assert "default" in THEME_PRESETS
    assert "synthwave" in THEME_PRESETS
    assert "matrix" in THEME_PRESETS
    assert "nord" in THEME_PRESETS

    for key, preset in THEME_PRESETS.items():
        assert "name" in preset, f"Preset {key} missing name"
        assert "description" in preset, f"Preset {key} missing description"
        assert "palette" in preset, f"Preset {key} missing palette"
        assert "hero" in preset, f"Preset {key} missing hero"
        # Validate that preset palette instantiates ColorPalette without error
        palette = ColorPalette(**preset["palette"])
        assert palette.background.startswith("#")


def test_theme_yaml_save_and_load(tmp_path: Path) -> None:
    test_file = tmp_path / "theme.yaml"
    with patch("clanker.config.theme.THEME_CONFIG_PATH", test_file):
        # When file doesn't exist, returns default
        cfg = get_theme_config()
        assert cfg.preset == "default"
        assert cfg.hero.animation_enabled is True

        # Modify and save
        cfg.preset = "synthwave"
        cfg.palette.background = "#0f0a1c"
        cfg.hero.gradient_start = "#ff2bd6"
        cfg.hero.gradient_end = "#a855f7"
        cfg.hero.animation_enabled = False
        save_theme_config(cfg)

        assert test_file.exists()

        # Load back
        loaded = get_theme_config()
        assert loaded.preset == "synthwave"
        assert loaded.palette.background == "#0f0a1c"
        assert loaded.hero.gradient_start == "#ff2bd6"
        assert loaded.hero.gradient_end == "#a855f7"
        assert loaded.hero.animation_enabled is False

        # Reset
        reset_cfg = reset_theme_config()
        assert reset_cfg.preset == "default"
        reloaded = get_theme_config()
        assert reloaded.preset == "default"


def test_generate_tcss() -> None:
    cfg = UIThemeConfig()
    cfg.palette.background = "#123456"
    cfg.palette.user_msg = "#ff00ff"
    cfg.palette.status_bar_bg = "#654321"

    tcss = generate_tcss(cfg)
    assert "Screen {" in tcss
    assert "ChatLog {" in tcss
    assert "StatusBar {" in tcss
    assert "WorkspaceStatus {" in tcss
    assert "PromptBar {" in tcss
    assert "rgb(18,52,86)" in tcss  # #123456
    assert "rgb(255,0,255)" in tcss  # #ff00ff
    assert "rgb(101,67,33)" in tcss  # #654321


def test_theme_api_endpoints(tmp_path: Path) -> None:
    test_file = tmp_path / "theme.yaml"
    with patch("clanker.config.theme.THEME_CONFIG_PATH", test_file):
        app = create_app()
        client = TestClient(app)

        # GET /api/theme
        get_res = client.get("/api/theme")
        assert get_res.status_code == 200
        data = get_res.json()
        assert data["theme"]["preset"] == "default"
        assert "default" in data["presets"]
        assert data["default_ascii_art"] == DEFAULT_ASCII_ART
        assert "CLNKR (Default)" in data["sample_ascii_arts"]

        # PUT /api/theme
        updated_theme = data["theme"]
        updated_theme["preset"] = "matrix"
        updated_theme["palette"]["background"] = "#050505"
        updated_theme["hero"]["animation_enabled"] = False
        updated_theme["hero"]["ascii_art"] = MINIMAL_ASCII_ART

        put_res = client.put("/api/theme", json=updated_theme)
        assert put_res.status_code == 200
        assert put_res.json()["success"] is True

        # Verify persisted via GET
        get_res2 = client.get("/api/theme")
        assert get_res2.status_code == 200
        data2 = get_res2.json()
        assert data2["theme"]["preset"] == "matrix"
        assert data2["theme"]["palette"]["background"] == "#050505"
        assert data2["theme"]["hero"]["animation_enabled"] is False
        assert data2["theme"]["hero"]["ascii_art"] == MINIMAL_ASCII_ART

        # POST /api/theme/reset
        reset_res = client.post("/api/theme/reset")
        assert reset_res.status_code == 200
        assert reset_res.json()["theme"]["preset"] == "default"


def test_hero_art_custom_theme() -> None:
    custom_hero = HeroTheme(
        ascii_art=ROBOT_ASCII_ART,
        animation_enabled=False,
        gradient_start="#ff0000",
        gradient_end="#00ff00",
        system_online_color="#ffff00",
        model_label_color="#aaaaaa",
        model_name_color="#00ffff",
    )

    hero = _HeroArt(hero_theme=custom_hero)
    hero.refresh = MagicMock()
    hero.set_art(ROBOT_ASCII_ART)
    hero.set_final(ROBOT_ASCII_ART, model_info="gpt-4o", yolo_mode=True)

    # When animation is disabled:
    assert hero._wave_settled is True
    assert hero._wave_offset(0) == 0
    assert hero._wave_offset(10) == 0

    # Gradient style uses custom colors
    style_str = hero._gradient_style(0, 0)
    assert style_str.startswith("rgb(")

    # Rendered text contains the custom ascii lines and text
    rendered = hero.render()
    text_content = rendered.plain
    assert "CLANKER" in text_content
    assert "Systems online" in text_content
    assert "gpt-4o" in text_content
    assert "YOLO MODE" in text_content


def test_hero_art_animation_toggle() -> None:
    theme_anim = HeroTheme(animation_enabled=True)
    hero = _HeroArt(hero_theme=theme_anim)
    hero.refresh = MagicMock()

    # Dynamic toggle off
    theme_static = HeroTheme(animation_enabled=False)
    hero.set_hero_theme(theme_static)
    assert hero._wave_settled is True
    assert hero._tick_timer is None
    assert hero._wave_offset(5) == 0


@pytest.mark.asyncio
async def test_clanker_app_theme_initialization() -> None:
    from rich.console import Console

    from clanker.ui.app import ClankerApp

    console = Console()
    app = ClankerApp(console, model_info="claude-3-7-sonnet")
    assert hasattr(app, "_theme_config")
    assert app.theme == "clanker"


def test_add_update_banner_themed() -> None:
    from clanker.ui.chat_log import ChatLog
    chat_log = ChatLog()
    custom_hero = HeroTheme(
        gradient_start="#ff2bd6",
        gradient_end="#00f0ff",
        model_name_color="#00f0ff",
        model_label_color="#f3e8ff",
    )
    chat_log.set_hero_theme(custom_hero)
    chat_log.mount = MagicMock()
    chat_log.add_update_banner("0.9.16", "0.9.24", "curl install.sh")
    assert len(chat_log._messages) == 1
    banner_widget = chat_log._messages[0]
    plain = banner_widget._Static__content.plain  # type: ignore[attr-defined]
    assert "UPDATE AVAILABLE" in plain
    assert "v0.9.16" in plain
    assert "v0.9.24" in plain
