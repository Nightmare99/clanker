"""File operation tools for reading, writing, and editing files."""

from pathlib import Path

from langchain.tools import tool

from clanker.config import get_settings
from clanker.utils.sandbox import is_path_safe
from clanker.utils.validators import validate_file_path

# Constants
MAX_LINES_DEFAULT = 2000
MAX_LINE_LENGTH = 2000


@tool
def read_file(file_path: str, offset: int = 0, limit: int = MAX_LINES_DEFAULT) -> str:
    """Read contents of a file with line numbers.

    Args:
        file_path: Absolute path to the file to read.
        offset: Line number to start reading from (0-indexed).
        limit: Maximum number of lines to read.

    Returns:
        File contents with line numbers, or an error message.
    """
    try:
        path = validate_file_path(file_path)
    except ValueError as e:
        return f"Error: {e}"

    if not path.exists():
        return f"Error: File not found: {file_path}"

    if not path.is_file():
        return f"Error: Not a file: {file_path}"

    settings = get_settings()
    if path.stat().st_size > settings.safety.max_file_size:
        return f"Error: File too large (>{settings.safety.max_file_size} bytes)"

    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        return f"Error reading file: {e}"

    # Apply offset and limit
    selected_lines = lines[offset : offset + limit]

    # Format with line numbers (1-indexed for display)
    result_lines = []
    for i, line in enumerate(selected_lines, start=offset + 1):
        # Truncate long lines
        if len(line) > MAX_LINE_LENGTH:
            line = line[: MAX_LINE_LENGTH - 3] + "...\n"
        result_lines.append(f"{i:6}\t{line.rstrip()}")

    if not result_lines:
        return "File is empty."

    result = "\n".join(result_lines)

    # Add indicator if truncated
    if offset + limit < len(lines):
        remaining = len(lines) - (offset + limit)
        result += f"\n\n... ({remaining} more lines)"

    return result


@tool
def write_file(file_path: str, content: str) -> str:
    """Write content to a file, creating it if it doesn't exist.

    Args:
        file_path: Absolute path to the file to write.
        content: Content to write to the file.

    Returns:
        Success message or error description.
    """
    try:
        path = validate_file_path(file_path)
    except ValueError as e:
        return f"Error: {e}"

    is_safe, reason = is_path_safe(str(path), for_write=True)
    if not is_safe:
        return f"Error: {reason}"

    try:
        # Create parent directories if needed
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        return f"Successfully wrote {len(content)} characters to {file_path}"
    except OSError as e:
        return f"Error writing file: {e}"


@tool
def edit_file(file_path: str, old_string: str, new_string: str) -> str:
    """Replace a string in a file with a new string.

    The old_string must be unique in the file to avoid ambiguous edits.

    Args:
        file_path: Absolute path to the file to edit.
        old_string: The exact text to find and replace.
        new_string: The text to replace it with.

    Returns:
        Success message or error description.
    """
    try:
        path = validate_file_path(file_path)
    except ValueError as e:
        return f"Error: {e}"

    if not path.exists():
        return f"Error: File not found: {file_path}"

    is_safe, reason = is_path_safe(str(path), for_write=True)
    if not is_safe:
        return f"Error: {reason}"

    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        return f"Error reading file: {e}"

    # Check uniqueness
    count = content.count(old_string)
    if count == 0:
        return f"Error: String not found in file: '{old_string[:100]}...'"
    if count > 1:
        return f"Error: String found {count} times. Provide more context for unique match."

    # Perform replacement
    new_content = content.replace(old_string, new_string, 1)

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return f"Successfully edited {file_path}"
    except OSError as e:
        return f"Error writing file: {e}"


@tool
def list_directory(path: str = ".") -> str:
    """List contents of a directory.

    Args:
        path: Path to the directory to list. Defaults to current directory.

    Returns:
        Directory listing with file types and sizes.
    """
    try:
        dir_path = validate_file_path(path)
    except ValueError as e:
        return f"Error: {e}"

    if not dir_path.exists():
        return f"Error: Directory not found: {path}"

    if not dir_path.is_dir():
        return f"Error: Not a directory: {path}"

    try:
        entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as e:
        return f"Error listing directory: {e}"

    if not entries:
        return "Directory is empty."

    lines = []
    for entry in entries:
        try:
            if entry.is_dir():
                lines.append(f"  [DIR]  {entry.name}/")
            elif entry.is_symlink():
                target = entry.resolve()
                lines.append(f"  [LINK] {entry.name} -> {target}")
            else:
                size = entry.stat().st_size
                size_str = _format_size(size)
                lines.append(f"  {size_str:>8}  {entry.name}")
        except OSError:
            lines.append(f"  [ERROR] {entry.name}")

    return f"{dir_path}:\n" + "\n".join(lines)


def _format_size(size: int) -> str:
    """Format file size in human-readable format."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"
