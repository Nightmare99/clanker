"""Command and path sandboxing utilities."""

import re
from pathlib import Path

# Commands that are always blocked
BLOCKED_COMMANDS = frozenset({
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    ":(){:|:&};:",  # Fork bomb
    "dd if=/dev/zero",
    "dd if=/dev/random",
    "> /dev/sda",
    "chmod -R 777 /",
})

# Patterns that indicate dangerous commands
DANGEROUS_PATTERNS = [
    re.compile(r"rm\s+-[rf]*\s+/(?!\S)"),  # rm -rf / (root)
    re.compile(r">\s*/dev/"),  # Writing to devices
    re.compile(r"mkfs\.\w+"),  # Filesystem formatting
    re.compile(r"dd\s+.*if=/dev/(?:zero|random|urandom).*of=/dev/"),  # dd to devices
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;"),  # Fork bomb variants
]

# Commands requiring user confirmation
CONFIRMATION_REQUIRED = frozenset({
    "rm",
    "mv",
    "git push",
    "git reset",
    "git rebase",
    "git checkout --",
    "chmod",
    "chown",
})

# Directories that should never be written to
PROTECTED_PATHS = frozenset({
    "/",
    "/bin",
    "/boot",
    "/dev",
    "/etc",
    "/lib",
    "/lib64",
    "/proc",
    "/root",
    "/sbin",
    "/sys",
    "/usr",
    "/var",
})


def is_command_safe(command: str) -> tuple[bool, str]:
    """
    Check if a command is safe to execute.

    Returns:
        Tuple of (is_safe, reason). If unsafe, reason explains why.
    """
    command_lower = command.lower().strip()

    # Check blocked commands
    for blocked in BLOCKED_COMMANDS:
        if blocked in command_lower:
            return False, f"Command contains blocked pattern: {blocked}"

    # Check dangerous patterns
    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(command):
            return False, f"Command matches dangerous pattern: {pattern.pattern}"

    return True, ""


def requires_confirmation(command: str) -> bool:
    """Check if a command requires user confirmation."""
    command_lower = command.lower().strip()
    return any(cmd in command_lower for cmd in CONFIRMATION_REQUIRED)


def is_path_safe(path: str | Path, for_write: bool = False) -> tuple[bool, str]:
    """
    Check if a file path is safe to access.

    Args:
        path: The path to check.
        for_write: If True, apply stricter checks for write operations.

    Returns:
        Tuple of (is_safe, reason). If unsafe, reason explains why.
    """
    try:
        resolved = Path(path).resolve()
    except (OSError, ValueError) as e:
        return False, f"Invalid path: {e}"

    path_str = str(resolved)

    # Check protected paths for write operations
    if for_write:
        for protected in PROTECTED_PATHS:
            if path_str == protected or path_str.startswith(protected + "/"):
                # Allow paths in user-writable subdirectories
                if not any(
                    path_str.startswith(p)
                    for p in ["/var/tmp", "/var/log"]
                ):
                    return False, f"Cannot write to protected path: {protected}"

    # Check for path traversal attempts
    if ".." in str(path):
        # Resolve and check it's still within expected bounds
        pass  # Path.resolve() handles this

    return True, ""


def sanitize_path(path: str) -> Path:
    """
    Sanitize and resolve a file path.

    Raises:
        ValueError: If the path is invalid or unsafe.
    """
    is_safe, reason = is_path_safe(path)
    if not is_safe:
        raise ValueError(reason)

    return Path(path).resolve()
