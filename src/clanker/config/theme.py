"""UI and TUI Theme customization configuration and utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# Storage path for UI theme configuration
THEME_CONFIG_PATH = Path.home() / ".clanker" / "theme.yaml"

DEFAULT_ASCII_ART = r""" ▄████████  ▄█       ███▄▄▄▄      ▄█   ▄█▄    ▄████████
███    ███ ███       ███▀▀▀██▄   ███ ▄███▀   ███    ███
███    █▀  ███       ███   ███   ███▐██▀     ███    ███
███        ███       ███   ███  ▄█████▀     ▄███▄▄▄▄██▀
███        ███       ███   ███ ▀▀█████▄    ▀▀███▀▀▀▀▀
███    █▄  ███       ███   ███   ███▐██▄   ▀███████████
███    ███ ███▌    ▄ ███   ███   ███ ▀███▄   ███    ███
████████▀  █████▄▄██  ▀█   █▀    ███   ▀█▀   ███    ███
           ▀                     ▀           ███    ███"""

MINIMAL_ASCII_ART = r"""  ____ _        _    _   _ _  _______ ____
 / ___| |      / \  | \ | | |/ / ____|  _ \
| |   | |     / _ \ |  \| | ' /|  _| | |_) |
| |___| |___ / ___ \| |\  | . \| |___|  _ <
 \____|_____/_/   \_\_| \_|_|\_\_____|_| \_\
"""

ROBOT_ASCII_ART = r"""   [o_o]   CLANKER
  /|_-_|\  =========
   | |     SYSTEMS READY
"""


def hex_to_rgb(hex_code: str) -> tuple[int, int, int]:
    """Convert hex string (#RRGGBB or #RGB or rgb(...)) to RGB tuple."""
    hex_code = hex_code.strip()
    if hex_code.startswith("rgb(") and hex_code.endswith(")"):
        parts = hex_code[4:-1].split(",")
        if len(parts) == 3:
            try:
                return (int(parts[0].strip()), int(parts[1].strip()), int(parts[2].strip()))
            except ValueError:
                pass
    cleaned = hex_code.lstrip("#")
    if len(cleaned) == 3:
        cleaned = "".join(c * 2 for c in cleaned)
    if len(cleaned) == 6:
        try:
            return (
                int(cleaned[0:2], 16),
                int(cleaned[2:4], 16),
                int(cleaned[4:6], 16),
            )
        except ValueError:
            pass
    return (0, 240, 240)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert RGB values to lowercase hex string."""
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))
    return f"#{r:02x}{g:02x}{b:02x}"


def rgb_str(hex_code: str) -> str:
    """Format hex color as rgb(r,g,b) string for Textual TCSS and Rich styles."""
    r, g, b = hex_to_rgb(hex_code)
    return f"rgb({r},{g},{b})"


def interpolate_color(start_hex: str, end_hex: str, factor: float) -> str:
    """Linearly interpolate between two hex colors by factor (0.0 to 1.0)."""
    factor = max(0.0, min(1.0, factor))
    r1, g1, b1 = hex_to_rgb(start_hex)
    r2, g2, b2 = hex_to_rgb(end_hex)
    r = int(r1 + (r2 - r1) * factor)
    g = int(g1 + (g2 - g1) * factor)
    b = int(b1 + (b2 - b1) * factor)
    return rgb_to_hex(r, g, b)


class ColorPalette(BaseModel):
    """Custom color palette for all TUI elements."""

    # General & Base
    background: str = Field(default="#000000", description="App screen background color")
    surface: str = Field(default="#0f0f0f", description="Cards, panels, and surfaces background")
    foreground: str = Field(default="#c8c8c8", description="Primary body text color")
    primary: str = Field(default="#b4ff3c", description="Primary brand accent color")
    secondary: str = Field(default="#00f0f0", description="Secondary accent color")

    # Status bars
    status_bar_bg: str = Field(default="#0f0f0f", description="Top status bar background color")
    status_bar_model: str = Field(default="#00f0f0", description="Model name in top status bar")
    status_bar_tokens: str = Field(default="#646464", description="Token info in top status bar")
    status_bar_subagents: str = Field(default="#00f0f0", description="Subagent counter in top status bar")
    bottom_bar_bg: str = Field(default="#000000", description="Bottom workspace status background color")
    bottom_bar_text: str = Field(default="#8c8c8c", description="Bottom workspace status text color")
    bottom_bar_session: str = Field(default="#b4ff3c", description="Session ID label in workspace status")
    bottom_bar_context: str = Field(default="#ffdc3c", description="Context compaction indicator color")

    # Text input area
    prompt_bar_bg: str = Field(default="#000000", description="Prompt bar background color")
    prompt_symbol: str = Field(default="#00f0f0", description="Prompt symbol (>) color")
    input_bg: str = Field(default="#000000", description="Input field background color")
    input_text: str = Field(default="#c8c8c8", description="Input field text color")
    queue_bg: str = Field(default="#000000", description="Message queue panel background")
    queue_text: str = Field(default="#969696", description="Message queue text color")
    todo_bg: str = Field(default="#000000", description="Todo list panel background")
    todo_text: str = Field(default="#b4b4b4", description="Todo list text color")

    # Output & Chat log
    chat_log_bg: str = Field(default="#000000", description="Chat log scroll area background")
    user_msg: str = Field(default="#00f0f0", description="User message text color")
    assistant_msg: str = Field(default="#c8c8c8", description="Assistant message text color")
    system_msg: str = Field(default="#00f0f0", description="System message text color")
    tool_card: str = Field(default="#c8c8c8", description="Tool card border and header color")
    thinking_card: str = Field(default="#b48cff", description="Thinking block border color")
    divider: str = Field(default="#00f0f0", description="Hero divider line color")
    turn_separator: str = Field(default="#3c3c50", description="Turn separator dashed rule color")

    # Notifications & Alerts
    notify_info: str = Field(default="#00f0f0", description="Info notification accent color")
    notify_success: str = Field(default="#b4ff3c", description="Success notification accent color")
    notify_warning: str = Field(default="#ffdc3c", description="Warning notification accent color")
    notify_error: str = Field(default="#ff69b4", description="Error notification accent color")


class HeroTheme(BaseModel):
    """Configuration for the Hero ASCII art banner and animation."""

    ascii_art: str = Field(
        default=DEFAULT_ASCII_ART,
        description="Custom ASCII art for the hero banner",
    )
    animation_enabled: bool = Field(
        default=True,
        description="Toggle animated shimmer / gradient bounce effect on/off",
    )
    gradient_start: str = Field(
        default="#00f0f0",
        description="Start color of the ASCII banner gradient wash",
    )
    gradient_end: str = Field(
        default="#0040ff",
        description="End color of the ASCII banner gradient wash",
    )
    system_online_color: str = Field(
        default="#00f0f0",
        description="Color of the 'Systems online' status text",
    )
    model_label_color: str = Field(
        default="#ffffff",
        description="Color of the 'Model:' label in the hero",
    )
    model_name_color: str = Field(
        default="#64beff",
        description="Color of the active model name in the hero",
    )


class UIThemeConfig(BaseModel):
    """Full UI style and theme configuration."""

    preset: str = Field(default="default", description="Active preset name or 'custom'")
    palette: ColorPalette = Field(default_factory=ColorPalette)
    hero: HeroTheme = Field(default_factory=HeroTheme)


# Built-in Theme Presets
THEME_PRESETS: dict[str, dict[str, Any]] = {
    "default": {
        "name": "Cyberpunk Clanker (Default)",
        "description": "Electric cyan, acid lime, and neon blue on deep black",
        "palette": {
            "background": "#000000",
            "surface": "#0f0f0f",
            "foreground": "#c8c8c8",
            "primary": "#b4ff3c",
            "secondary": "#00f0f0",
            "status_bar_bg": "#0f0f0f",
            "status_bar_model": "#00f0f0",
            "status_bar_tokens": "#646464",
            "status_bar_subagents": "#00f0f0",
            "bottom_bar_bg": "#000000",
            "bottom_bar_text": "#8c8c8c",
            "bottom_bar_session": "#b4ff3c",
            "bottom_bar_context": "#ffdc3c",
            "prompt_bar_bg": "#000000",
            "prompt_symbol": "#00f0f0",
            "input_bg": "#000000",
            "input_text": "#c8c8c8",
            "queue_bg": "#000000",
            "queue_text": "#969696",
            "todo_bg": "#000000",
            "todo_text": "#b4b4b4",
            "chat_log_bg": "#000000",
            "user_msg": "#00f0f0",
            "assistant_msg": "#c8c8c8",
            "system_msg": "#00f0f0",
            "tool_card": "#c8c8c8",
            "thinking_card": "#b48cff",
            "divider": "#00f0f0",
            "turn_separator": "#3c3c50",
            "notify_info": "#00f0f0",
            "notify_success": "#b4ff3c",
            "notify_warning": "#ffdc3c",
            "notify_error": "#ff69b4",
        },
        "hero": {
            "animation_enabled": True,
            "gradient_start": "#00f0f0",
            "gradient_end": "#0040ff",
            "system_online_color": "#00f0f0",
            "model_label_color": "#ffffff",
            "model_name_color": "#64beff",
        },
    },
    "synthwave": {
        "name": "Synthwave Neon",
        "description": "Vibrant magenta, electric violet, and cyan on midnight violet",
        "palette": {
            "background": "#0f0a1c",
            "surface": "#1a122e",
            "foreground": "#e2d9f3",
            "primary": "#ff2bd6",
            "secondary": "#00f0ff",
            "status_bar_bg": "#1a122e",
            "status_bar_model": "#ff2bd6",
            "status_bar_tokens": "#8b7fa8",
            "status_bar_subagents": "#00f0ff",
            "bottom_bar_bg": "#0f0a1c",
            "bottom_bar_text": "#8b7fa8",
            "bottom_bar_session": "#ff2bd6",
            "bottom_bar_context": "#f59e0b",
            "prompt_bar_bg": "#0f0a1c",
            "prompt_symbol": "#ff2bd6",
            "input_bg": "#0f0a1c",
            "input_text": "#e2d9f3",
            "queue_bg": "#140e26",
            "queue_text": "#a78bfa",
            "todo_bg": "#140e26",
            "todo_text": "#c4b5fd",
            "chat_log_bg": "#0f0a1c",
            "user_msg": "#ff2bd6",
            "assistant_msg": "#e2d9f3",
            "system_msg": "#00f0ff",
            "tool_card": "#a78bfa",
            "thinking_card": "#c084fc",
            "divider": "#ff2bd6",
            "turn_separator": "#4c1d95",
            "notify_info": "#00f0ff",
            "notify_success": "#10b981",
            "notify_warning": "#f59e0b",
            "notify_error": "#f43f5e",
        },
        "hero": {
            "animation_enabled": True,
            "gradient_start": "#ff2bd6",
            "gradient_end": "#a855f7",
            "system_online_color": "#ff2bd6",
            "model_label_color": "#f3e8ff",
            "model_name_color": "#00f0ff",
        },
    },
    "matrix": {
        "name": "Matrix Terminal",
        "description": "Classic phosphor green and deep cyber emerald on obsidian black",
        "palette": {
            "background": "#050a05",
            "surface": "#0a140a",
            "foreground": "#86efac",
            "primary": "#22c55e",
            "secondary": "#4ade80",
            "status_bar_bg": "#0a140a",
            "status_bar_model": "#22c55e",
            "status_bar_tokens": "#166534",
            "status_bar_subagents": "#4ade80",
            "bottom_bar_bg": "#050a05",
            "bottom_bar_text": "#15803d",
            "bottom_bar_session": "#22c55e",
            "bottom_bar_context": "#eab308",
            "prompt_bar_bg": "#050a05",
            "prompt_symbol": "#22c55e",
            "input_bg": "#050a05",
            "input_text": "#86efac",
            "queue_bg": "#081008",
            "queue_text": "#4ade80",
            "todo_bg": "#081008",
            "todo_text": "#86efac",
            "chat_log_bg": "#050a05",
            "user_msg": "#4ade80",
            "assistant_msg": "#bbf7d0",
            "system_msg": "#22c55e",
            "tool_card": "#15803d",
            "thinking_card": "#16a34a",
            "divider": "#22c55e",
            "turn_separator": "#14532d",
            "notify_info": "#4ade80",
            "notify_success": "#22c55e",
            "notify_warning": "#facc15",
            "notify_error": "#ef4444",
        },
        "hero": {
            "animation_enabled": True,
            "gradient_start": "#22c55e",
            "gradient_end": "#86efac",
            "system_online_color": "#22c55e",
            "model_label_color": "#dcfce7",
            "model_name_color": "#4ade80",
        },
    },
    "nord": {
        "name": "Nordic Frost",
        "description": "Arctic polar night, glacier blue, and snow white",
        "palette": {
            "background": "#242933",
            "surface": "#2e3440",
            "foreground": "#eceff4",
            "primary": "#88c0d0",
            "secondary": "#81a1c1",
            "status_bar_bg": "#2e3440",
            "status_bar_model": "#88c0d0",
            "status_bar_tokens": "#7b88a1",
            "status_bar_subagents": "#81a1c1",
            "bottom_bar_bg": "#242933",
            "bottom_bar_text": "#7b88a1",
            "bottom_bar_session": "#88c0d0",
            "bottom_bar_context": "#ebcb8b",
            "prompt_bar_bg": "#242933",
            "prompt_symbol": "#88c0d0",
            "input_bg": "#242933",
            "input_text": "#eceff4",
            "queue_bg": "#2a303c",
            "queue_text": "#d8dee9",
            "todo_bg": "#2a303c",
            "todo_text": "#eceff4",
            "chat_log_bg": "#242933",
            "user_msg": "#88c0d0",
            "assistant_msg": "#eceff4",
            "system_msg": "#81a1c1",
            "tool_card": "#4c566a",
            "thinking_card": "#b48ead",
            "divider": "#88c0d0",
            "turn_separator": "#434c5e",
            "notify_info": "#81a1c1",
            "notify_success": "#a3be8c",
            "notify_warning": "#ebcb8b",
            "notify_error": "#bf616a",
        },
        "hero": {
            "animation_enabled": True,
            "gradient_start": "#88c0d0",
            "gradient_end": "#5e81ac",
            "system_online_color": "#88c0d0",
            "model_label_color": "#eceff4",
            "model_name_color": "#81a1c1",
        },
    },
    "dracula": {
        "name": "Dracula Night",
        "description": "Gothic purple, hot pink, and mint cyan on midnight slate",
        "palette": {
            "background": "#1e1f29",
            "surface": "#282a36",
            "foreground": "#f8f8f2",
            "primary": "#bd93f9",
            "secondary": "#ff79c6",
            "status_bar_bg": "#282a36",
            "status_bar_model": "#bd93f9",
            "status_bar_tokens": "#6272a4",
            "status_bar_subagents": "#8be9fd",
            "bottom_bar_bg": "#1e1f29",
            "bottom_bar_text": "#6272a4",
            "bottom_bar_session": "#ff79c6",
            "bottom_bar_context": "#f1fa8c",
            "prompt_bar_bg": "#1e1f29",
            "prompt_symbol": "#bd93f9",
            "input_bg": "#1e1f29",
            "input_text": "#f8f8f2",
            "queue_bg": "#242633",
            "queue_text": "#f8f8f2",
            "todo_bg": "#242633",
            "todo_text": "#f8f8f2",
            "chat_log_bg": "#1e1f29",
            "user_msg": "#bd93f9",
            "assistant_msg": "#f8f8f2",
            "system_msg": "#8be9fd",
            "tool_card": "#6272a4",
            "thinking_card": "#ff79c6",
            "divider": "#bd93f9",
            "turn_separator": "#44475a",
            "notify_info": "#8be9fd",
            "notify_success": "#50fa7b",
            "notify_warning": "#f1fa8c",
            "notify_error": "#ff5555",
        },
        "hero": {
            "animation_enabled": True,
            "gradient_start": "#bd93f9",
            "gradient_end": "#ff79c6",
            "system_online_color": "#bd93f9",
            "model_label_color": "#f8f8f2",
            "model_name_color": "#8be9fd",
        },
    },
    "solarized": {
        "name": "Solarized Amber",
        "description": "Warm amber, vibrant orange, and teal on deep oceanic cyan",
        "palette": {
            "background": "#00212b",
            "surface": "#002b36",
            "foreground": "#93a1a1",
            "primary": "#b58900",
            "secondary": "#2aa198",
            "status_bar_bg": "#002b36",
            "status_bar_model": "#b58900",
            "status_bar_tokens": "#586e75",
            "status_bar_subagents": "#2aa198",
            "bottom_bar_bg": "#00212b",
            "bottom_bar_text": "#586e75",
            "bottom_bar_session": "#cb4b16",
            "bottom_bar_context": "#b58900",
            "prompt_bar_bg": "#00212b",
            "prompt_symbol": "#b58900",
            "input_bg": "#00212b",
            "input_text": "#93a1a1",
            "queue_bg": "#002630",
            "queue_text": "#839496",
            "todo_bg": "#002630",
            "todo_text": "#93a1a1",
            "chat_log_bg": "#00212b",
            "user_msg": "#2aa198",
            "assistant_msg": "#93a1a1",
            "system_msg": "#268bd2",
            "tool_card": "#586e75",
            "thinking_card": "#6c71c4",
            "divider": "#b58900",
            "turn_separator": "#073642",
            "notify_info": "#268bd2",
            "notify_success": "#859900",
            "notify_warning": "#b58900",
            "notify_error": "#dc322f",
        },
        "hero": {
            "animation_enabled": True,
            "gradient_start": "#b58900",
            "gradient_end": "#cb4b16",
            "system_online_color": "#b58900",
            "model_label_color": "#eee8d5",
            "model_name_color": "#2aa198",
        },
    },
    "monochrome": {
        "name": "Monochrome Minimal",
        "description": "Crisp slate greys, stark whites, and minimal dark tones",
        "palette": {
            "background": "#0a0a0c",
            "surface": "#141418",
            "foreground": "#e4e4e7",
            "primary": "#ffffff",
            "secondary": "#a1a1aa",
            "status_bar_bg": "#141418",
            "status_bar_model": "#ffffff",
            "status_bar_tokens": "#71717a",
            "status_bar_subagents": "#d4d4d8",
            "bottom_bar_bg": "#0a0a0c",
            "bottom_bar_text": "#71717a",
            "bottom_bar_session": "#ffffff",
            "bottom_bar_context": "#d4d4d8",
            "prompt_bar_bg": "#0a0a0c",
            "prompt_symbol": "#ffffff",
            "input_bg": "#0a0a0c",
            "input_text": "#e4e4e7",
            "queue_bg": "#101014",
            "queue_text": "#a1a1aa",
            "todo_bg": "#101014",
            "todo_text": "#e4e4e7",
            "chat_log_bg": "#0a0a0c",
            "user_msg": "#ffffff",
            "assistant_msg": "#e4e4e7",
            "system_msg": "#a1a1aa",
            "tool_card": "#71717a",
            "thinking_card": "#a1a1aa",
            "divider": "#ffffff",
            "turn_separator": "#27272a",
            "notify_info": "#d4d4d8",
            "notify_success": "#ffffff",
            "notify_warning": "#a1a1aa",
            "notify_error": "#ef4444",
        },
        "hero": {
            "animation_enabled": False,
            "gradient_start": "#ffffff",
            "gradient_end": "#71717a",
            "system_online_color": "#ffffff",
            "model_label_color": "#a1a1aa",
            "model_name_color": "#ffffff",
        },
    },
}


def get_theme_config() -> UIThemeConfig:
    """Load UIThemeConfig from ~/.clanker/theme.yaml or return default."""
    if not THEME_CONFIG_PATH.exists():
        return UIThemeConfig()
    try:
        with open(THEME_CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return UIThemeConfig()
        return UIThemeConfig(**data)
    except Exception:
        return UIThemeConfig()


def save_theme_config(config: UIThemeConfig) -> None:
    """Save UIThemeConfig to ~/.clanker/theme.yaml."""
    THEME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = config.model_dump()
    with open(THEME_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


def reset_theme_config() -> UIThemeConfig:
    """Reset ~/.clanker/theme.yaml to defaults."""
    default_config = UIThemeConfig()
    save_theme_config(default_config)
    return default_config


def generate_tcss(theme: UIThemeConfig) -> str:
    """Generate dynamic Textual TCSS override rules from the theme configuration."""
    p = theme.palette
    return f"""
/* Generated Clanker Theme Overrides */
Screen {{
    layers: base menu overlay;
    background: {rgb_str(p.background)};
    color: {rgb_str(p.foreground)};
}}

ChatLog {{
    background: {rgb_str(p.chat_log_bg)};
    padding: 0 1 1 1;
    margin: 0;
}}

ChatLog .msg-user {{
    color: {rgb_str(p.user_msg)};
}}

ChatLog .msg-assistant {{
    color: {rgb_str(p.assistant_msg)};
}}

ChatLog .msg-system {{
    color: {rgb_str(p.system_msg)};
}}

ChatLog .msg-info {{
    color: {rgb_str(p.notify_info)};
}}

ChatLog .msg-success {{
    color: {rgb_str(p.notify_success)};
}}

ChatLog .msg-warning {{
    color: {rgb_str(p.notify_warning)};
}}

ChatLog .msg-error {{
    color: {rgb_str(p.notify_error)};
}}

ChatLog .notify-info {{
    border-left: thick {rgb_str(p.notify_info)};
}}

ChatLog .notify-success {{
    border-left: thick {rgb_str(p.notify_success)};
}}

ChatLog .notify-warning {{
    border-left: thick {rgb_str(p.notify_warning)};
}}

ChatLog .notify-error {{
    border-left: thick {rgb_str(p.notify_error)};
}}

ChatLog .thinking-card {{
    border-left: solid {rgb_str(p.thinking_card)};
}}

ChatLog .tool-card {{
    border-left: solid {rgb_str(p.tool_card)};
}}

ChatLog > Rule.hero-divider,
ChatLog Rule.hero-divider {{
    color: {rgb_str(p.divider)};
}}

ChatLog > Rule.dashed,
ChatLog Rule.dashed {{
    color: {rgb_str(p.turn_separator)};
}}

ChatLog > Rule,
ChatLog Rule {{
    color: {rgb_str(p.turn_separator)};
}}

MarkdownHorizontalRule {{
    border-bottom: solid {rgb_str(p.turn_separator)};
}}

MarkdownBlockQuote {{
    background: {rgb_str(p.surface)};
    border-left: outer {rgb_str(p.primary)};
    color: {rgb_str(p.foreground)};
}}

MarkdownFence {{
    background: {rgb_str(p.surface)};
    color: {rgb_str(p.foreground)};
}}

StatusBar {{
    height: auto;
    background: {rgb_str(p.status_bar_bg)};
    border: none;
    border-bottom: tab {rgb_str(p.turn_separator)};
    margin: 0;
    padding: 0 1;
}}

StatusBar #status-subagents {{
    width: 1fr;
    height: 1;
    text-align: left;
    text-wrap: nowrap;
    text-overflow: ellipsis;
    color: {rgb_str(p.status_bar_subagents)};
}}

StatusBar #status-tokens {{
    width: auto;
    height: 1;
    text-align: center;
    text-wrap: nowrap;
    color: {rgb_str(p.status_bar_tokens)};
}}

StatusBar #status-model {{
    width: 1fr;
    height: 1;
    text-align: right;
    text-wrap: nowrap;
    text-overflow: ellipsis;
    color: {rgb_str(p.status_bar_model)};
}}

#input-area {{
    dock: bottom;
    height: auto;
    border-top: solid {rgb_str(p.turn_separator)};
}}

WorkspaceStatus {{
    background: {rgb_str(p.bottom_bar_bg)};
    color: {rgb_str(p.bottom_bar_text)};
}}

#workspace-shortcuts {{
    background: {rgb_str(p.bottom_bar_bg)};
    color: {rgb_str(p.bottom_bar_text)};
}}

WorkspaceStatus #status-session {{
    color: {rgb_str(p.bottom_bar_session)};
}}

WorkspaceStatus #status-context {{
    color: {rgb_str(p.bottom_bar_context)};
}}

PromptBar {{
    background: transparent;
    margin: 0 0 1 0;
}}

PromptBar #prompt-symbol {{
    color: {rgb_str(p.prompt_symbol)};
    background: transparent;
}}

PromptBar #prompt-input,
PromptBar #prompt-input:focus,
PromptBar #prompt-input:hover {{
    background: transparent;
    color: {rgb_str(p.input_text)};
}}

MessageQueue {{
    background: {rgb_str(p.queue_bg)};
    color: {rgb_str(p.queue_text)};
}}

TodoPanel {{
    background: {rgb_str(p.todo_bg)};
    color: {rgb_str(p.todo_text)};
}}

/* Update-available banner */
ChatLog .update-banner {{
    border: round {rgb_str(p.primary)};
    background: {rgb_str(p.surface)};
}}

/* Modals & Dialogs (F1 to F6, pickers, and task prompt) */
ShortcutHelpScreen > VerticalScroll {{
    border: round {rgb_str(p.primary)};
    background: {rgb_str(p.surface)};
    color: {rgb_str(p.foreground)};
}}

SubagentHistoryScreen > #subagent-modal {{
    border: round {rgb_str(p.primary)};
    background: {rgb_str(p.surface)};
}}

SubagentHistoryScreen #subagent-list {{
    border-right: solid {rgb_str(p.turn_separator)};
    background: {rgb_str(p.background)};
}}

SubagentHistoryScreen #subagent-detail {{
    background: {rgb_str(p.surface)};
    color: {rgb_str(p.foreground)};
}}

SubagentHistoryScreen ListView {{
    background: {rgb_str(p.background)};
}}

SubagentHistoryScreen ListItem {{
    background: {rgb_str(p.background)};
    color: {rgb_str(p.foreground)};
}}

SubagentHistoryScreen ListItem.--highlight {{
    background: {rgb_str(p.surface)};
    color: {rgb_str(p.primary)};
}}

HistoryScreen > #history-modal {{
    border: round {rgb_str(p.primary)};
    background: {rgb_str(p.surface)};
}}

HistoryScreen #history-header {{
    border-bottom: solid {rgb_str(p.turn_separator)};
    color: {rgb_str(p.secondary)};
}}

HistoryScreen #history-scroll {{
    background: {rgb_str(p.background)};
    color: {rgb_str(p.foreground)};
}}

ChangesScreen #changes-modal {{
    border: round {rgb_str(p.primary)};
    background: {rgb_str(p.surface)};
}}

ChangesScreen #changes-header {{
    border-bottom: solid {rgb_str(p.turn_separator)};
    color: {rgb_str(p.secondary)};
}}

ChangesScreen #changes-list {{
    border-right: solid {rgb_str(p.turn_separator)};
    background: {rgb_str(p.background)};
}}

ChangesScreen #changes-detail {{
    background: {rgb_str(p.surface)};
    color: {rgb_str(p.foreground)};
}}

MessageComposer #composer {{
    border: round {rgb_str(p.primary)};
    background: {rgb_str(p.surface)};
}}

MessageComposer #composer-title {{
    color: {rgb_str(p.secondary)};
}}

MessageComposer TextArea {{
    background: {rgb_str(p.input_bg)};
    color: {rgb_str(p.input_text)};
}}

MemoryScreen #memory-modal {{
    border: round {rgb_str(p.primary)};
    background: {rgb_str(p.surface)};
}}

MemoryScreen #memory-title {{
    color: {rgb_str(p.secondary)};
}}

MemoryScreen #memory-list {{
    background: {rgb_str(p.background)};
}}

MemoryScreen #memory-preview {{
    background: {rgb_str(p.surface)};
    color: {rgb_str(p.foreground)};
}}

MemoryScreen #memory-status {{
    color: {rgb_str(p.bottom_bar_text)};
}}

_PagedScreen > #picker-modal {{
    border: round {rgb_str(p.primary)};
    background: {rgb_str(p.surface)};
}}

_PagedScreen #picker-title {{
    color: {rgb_str(p.secondary)};
}}

_PagedScreen #picker-help {{
    color: {rgb_str(p.bottom_bar_text)};
}}

_PagedScreen #picker-page {{
    color: {rgb_str(p.bottom_bar_text)};
}}

_PagedScreen #picker-list {{
    background: {rgb_str(p.background)};
}}

_PagedScreen ListItem {{
    background: {rgb_str(p.background)};
    color: {rgb_str(p.foreground)};
}}

_PagedScreen ListItem.--highlight {{
    background: {rgb_str(p.surface)};
    color: {rgb_str(p.primary)};
}}

TaskPromptScreen #task-question {{
    border: round {rgb_str(p.primary)};
    background: {rgb_str(p.surface)};
    color: {rgb_str(p.foreground)};
}}

CompletionMenu {{
    background: {rgb_str(p.surface)};
    border: round {rgb_str(p.primary)};
    color: {rgb_str(p.foreground)};
}}
"""
