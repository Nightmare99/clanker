"""Runtime state for Clanker session."""

import json
from pathlib import Path

# Copilot model config file path
COPILOT_MODEL_PATH = Path.home() / ".clanker" / "copilot_default_model.json"

# Default Copilot model
DEFAULT_COPILOT_MODEL = "gpt-4.1"

# Valid reasoning effort levels
REASONING_EFFORT_LEVELS = ("low", "medium", "high", "xhigh")

# Yolo mode - when True, bash commands execute without approval
_yolo_mode: bool = False

# Copilot mode - when True, use GitHub Copilot SDK for session management
_copilot_mode: bool = False

# Current Copilot model and reasoning effort (loaded from file or default)
_copilot_model: str | None = None
_copilot_reasoning_effort: str | None = None


def set_yolo_mode(enabled: bool) -> None:
    """Set yolo mode (bypass command approval)."""
    global _yolo_mode
    _yolo_mode = enabled


def is_yolo_mode() -> bool:
    """Check if yolo mode is enabled."""
    return _yolo_mode


def set_copilot_mode(enabled: bool) -> None:
    """Set Copilot mode (use GitHub Copilot SDK for sessions)."""
    global _copilot_mode
    _copilot_mode = enabled


def is_copilot_mode() -> bool:
    """Check if Copilot mode is enabled."""
    return _copilot_mode


def _load_copilot_config() -> tuple[str, str | None]:
    """Load the default Copilot model and reasoning effort from file.

    Returns:
        Tuple of (model_id, reasoning_effort).
    """
    # Try new JSON format first
    if COPILOT_MODEL_PATH.exists():
        try:
            data = json.loads(COPILOT_MODEL_PATH.read_text())
            model = data.get("model", DEFAULT_COPILOT_MODEL)
            effort = data.get("reasoning_effort")
            return model, effort
        except (json.JSONDecodeError, Exception):
            pass

    # Fall back to old plain text format (migration)
    old_path = COPILOT_MODEL_PATH.with_suffix("")
    if old_path.exists():
        try:
            model = old_path.read_text().strip()
            if model:
                return model, None
        except Exception:
            pass

    return DEFAULT_COPILOT_MODEL, None


def _save_copilot_config(model: str, reasoning_effort: str | None) -> None:
    """Save the default Copilot model and reasoning effort to file."""
    try:
        COPILOT_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {"model": model}
        if reasoning_effort:
            data["reasoning_effort"] = reasoning_effort
        COPILOT_MODEL_PATH.write_text(json.dumps(data))
    except Exception:
        pass  # Silently fail if we can't save


def set_copilot_model(model: str, reasoning_effort: str | None = None) -> None:
    """Set the current Copilot model and reasoning effort, and persist it."""
    global _copilot_model, _copilot_reasoning_effort
    _copilot_model = model
    _copilot_reasoning_effort = reasoning_effort
    _save_copilot_config(model, reasoning_effort)


def get_copilot_model() -> str:
    """Get the current Copilot model (loads from file if not set)."""
    global _copilot_model, _copilot_reasoning_effort
    if _copilot_model is None:
        _copilot_model, _copilot_reasoning_effort = _load_copilot_config()
    return _copilot_model


def get_copilot_reasoning_effort() -> str | None:
    """Get the current Copilot reasoning effort (loads from file if not set)."""
    global _copilot_model, _copilot_reasoning_effort
    if _copilot_model is None:
        _copilot_model, _copilot_reasoning_effort = _load_copilot_config()
    return _copilot_reasoning_effort


def parse_model_selection(selection: str) -> tuple[str, str | None]:
    """Parse a model selection string into model ID and reasoning effort.

    Handles formats like:
    - "gpt-4.1" -> ("gpt-4.1", None)
    - "claude-sonnet-4 (high)" -> ("claude-sonnet-4", "high")
    - "o3 (xhigh)" -> ("o3", "xhigh")

    Args:
        selection: The model selection string.

    Returns:
        Tuple of (model_id, reasoning_effort).
    """
    selection = selection.strip()

    # Check for reasoning effort suffix like " (high)"
    if selection.endswith(")") and " (" in selection:
        base, effort_part = selection.rsplit(" (", 1)
        effort = effort_part.rstrip(")")
        if effort in REASONING_EFFORT_LEVELS:
            return base, effort

    return selection, None


def format_model_display(model: str, reasoning_effort: str | None) -> str:
    """Format model and reasoning effort for display.

    Args:
        model: The model ID.
        reasoning_effort: Optional reasoning effort level.

    Returns:
        Formatted string like "gpt-4.1" or "claude-sonnet-4 (high)".
    """
    if reasoning_effort:
        return f"{model} ({reasoning_effort})"
    return model
