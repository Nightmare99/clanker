"""Runtime state for Clanker session."""

from pathlib import Path

# Copilot model config file path
COPILOT_MODEL_PATH = Path.home() / ".clanker" / "copilot_default_model"

# Default Copilot model
DEFAULT_COPILOT_MODEL = "gpt-4.1"

# Yolo mode - when True, bash commands execute without approval
_yolo_mode: bool = False

# Copilot mode - when True, use GitHub Copilot SDK for session management
_copilot_mode: bool = False

# Current Copilot model (loaded from file or default)
_copilot_model: str | None = None


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


def _load_copilot_model() -> str:
    """Load the default Copilot model from file."""
    if COPILOT_MODEL_PATH.exists():
        try:
            model = COPILOT_MODEL_PATH.read_text().strip()
            if model:
                return model
        except Exception:
            pass
    return DEFAULT_COPILOT_MODEL


def _save_copilot_model(model: str) -> None:
    """Save the default Copilot model to file."""
    try:
        COPILOT_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        COPILOT_MODEL_PATH.write_text(model)
    except Exception:
        pass  # Silently fail if we can't save


def set_copilot_model(model: str) -> None:
    """Set the current Copilot model and persist it."""
    global _copilot_model
    _copilot_model = model
    _save_copilot_model(model)


def get_copilot_model() -> str:
    """Get the current Copilot model (loads from file if not set)."""
    global _copilot_model
    if _copilot_model is None:
        _copilot_model = _load_copilot_model()
    return _copilot_model
