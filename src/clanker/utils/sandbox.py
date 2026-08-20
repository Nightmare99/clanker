"""Command and path sandboxing utilities."""

import re
import tempfile
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


def _resolve_or_self(path_str: str) -> str:
    """Resolve *path_str* through symlinks, falling back to itself on error."""
    try:
        return str(Path(path_str).resolve())
    except OSError:
        return path_str


# Pre-resolved through symlinks, matching how the input path is resolved in
# is_path_safe() below. On macOS, /etc, /var, /tmp, etc. are symlinks into
# /private/... -- comparing a resolved input path against these LITERAL,
# unresolved labels would silently let writes through (e.g. "/etc/passwd"
# resolves to "/private/etc/passwd", which doesn't start with "/etc/"). Keyed
# by the original label so error messages stay readable ("/etc", not
# "/private/etc").
_PROTECTED_PATHS_RESOLVED: dict[str, str] = {p: _resolve_or_self(p) for p in PROTECTED_PATHS}

# tempfile.gettempdir() is included because on macOS it (and anything under
# it, including pytest's own tmp_path fixture) resolves to /private/var/...
# -- the same prefix as the protected "/var" entry -- so without this
# exception, ordinary temp-file writes (e.g. spawn_subagent's truncated-
# output files) would be wrongly blocked on macOS.
_WRITE_EXCEPTIONS_RESOLVED: tuple[str, ...] = tuple(
    _resolve_or_self(p) for p in ("/var/tmp", "/var/log", tempfile.gettempdir())
)


def is_command_safe(command: str, extra_blacklist: list[str] | None = None) -> tuple[bool, str]:
    """
    Check if a command is safe to execute.

    Args:
        command: The command string to check.
        extra_blacklist: Optional user-configured substrings (system + project).
            A command is blocked if any entry is a case-insensitive substring of
            it. Applied in addition to the built-in blocked commands/patterns.

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

    # Check the user-configured blacklist (system-wide + project), substring match
    if extra_blacklist:
        for entry in extra_blacklist:
            needle = entry.lower().strip()
            if needle and needle in command_lower:
                return False, f"Command is blacklisted: {entry}"

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
        for protected, protected_resolved in _PROTECTED_PATHS_RESOLVED.items():
            if (
                (path_str == protected_resolved or path_str.startswith(protected_resolved + "/"))
                and not any(path_str.startswith(p) for p in _WRITE_EXCEPTIONS_RESOLVED)
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
