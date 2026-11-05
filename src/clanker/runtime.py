"""Runtime state for Clanker session."""

"""Runtime mode flags and execution state."""

# Yolo mode - when True, bash commands execute without approval
_yolo_mode: bool = False

# Loop mode - when active, agent continuously iterates on a goal until manually interrupted
_loop_mode: bool = False
_loop_goal: str = ""
_last_loop_goal: str = ""


def set_yolo_mode(enabled: bool) -> None:
    """Set yolo mode (bypass command approval)."""
    global _yolo_mode
    _yolo_mode = enabled


def is_yolo_mode() -> bool:
    """Check if yolo mode is enabled."""
    return _yolo_mode


def set_loop_mode(enabled: bool, goal: str = "") -> None:
    """Set or clear continuous loop mode."""
    global _loop_mode, _loop_goal, _last_loop_goal
    _loop_mode = enabled
    if enabled:
        if goal.strip():
            _loop_goal = goal.strip()
            _last_loop_goal = _loop_goal
        elif _last_loop_goal:
            _loop_goal = _last_loop_goal
    else:
        _loop_goal = ""


def is_loop_mode() -> bool:
    """Check if continuous loop mode is active."""
    return _loop_mode


def get_loop_goal() -> str:
    """Get the active goal for continuous loop mode."""
    return _loop_goal


def get_last_loop_goal() -> str:
    """Get the last active goal for continuous loop mode."""
    return _last_loop_goal or _loop_goal
