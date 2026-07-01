"""Runtime state for Clanker session."""

# Yolo mode - when True, bash commands execute without approval
_yolo_mode: bool = False


def set_yolo_mode(enabled: bool) -> None:
    """Set yolo mode (bypass command approval)."""
    global _yolo_mode
    _yolo_mode = enabled


def is_yolo_mode() -> bool:
    """Check if yolo mode is enabled."""
    return _yolo_mode
