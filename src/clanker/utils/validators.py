"""Input validation utilities."""

import re
from pathlib import Path


def validate_file_path(path: str) -> Path:
    """
    Validate and normalize a file path.

    Args:
        path: The file path to validate.

    Returns:
        A resolved Path object.

    Raises:
        ValueError: If the path is invalid.
    """
    if not path or not path.strip():
        raise ValueError("Path cannot be empty")

    # Remove null bytes and other dangerous characters
    cleaned = path.replace("\x00", "").strip()

    if not cleaned:
        raise ValueError("Path contains only invalid characters")

    try:
        return Path(cleaned).expanduser().resolve()
    except (OSError, RuntimeError) as e:
        raise ValueError(f"Invalid path '{path}': {e}") from e


def validate_glob_pattern(pattern: str) -> str:
    """
    Validate a glob pattern.

    Args:
        pattern: The glob pattern to validate.

    Returns:
        The validated pattern.

    Raises:
        ValueError: If the pattern is invalid.
    """
    if not pattern or not pattern.strip():
        raise ValueError("Pattern cannot be empty")

    # Basic pattern validation
    invalid_chars = re.compile(r"[\x00]")
    if invalid_chars.search(pattern):
        raise ValueError("Pattern contains invalid characters")

    return pattern.strip()


def validate_regex_pattern(pattern: str) -> re.Pattern[str]:
    """
    Validate and compile a regex pattern.

    Args:
        pattern: The regex pattern to validate.

    Returns:
        A compiled regex pattern.

    Raises:
        ValueError: If the pattern is invalid.
    """
    if not pattern:
        raise ValueError("Pattern cannot be empty")

    try:
        return re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern '{pattern}': {e}") from e


def validate_positive_int(value: int, name: str = "value") -> int:
    """
    Validate that a value is a positive integer.

    Args:
        value: The value to validate.
        name: Name of the parameter (for error messages).

    Returns:
        The validated value.

    Raises:
        ValueError: If the value is not positive.
    """
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer, got {value}")
    return value
