"""Platform conventions shared by TUI bindings and shortcut labels."""

import sys


def is_macos() -> bool:
    return sys.platform == "darwin"


def edit_key(key: str) -> str:
    """Return the terminal key name for a conventional editing shortcut."""
    return f"{'super' if is_macos() else 'ctrl'}+{key}"


def edit_label(key: str) -> str:
    return f"{'Cmd' if is_macos() else 'Ctrl'}+{key}"
