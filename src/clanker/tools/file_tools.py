"""File operation tools for reading, writing, and editing files."""

from itertools import islice
from pathlib import Path

from langchain.tools import tool

from clanker.config import get_settings
from clanker.logging import get_logger
from clanker.utils.sandbox import is_path_safe
from clanker.utils.validators import validate_file_path

# Module logger
logger = get_logger("tools.file")

# Constants
MAX_LINES_DEFAULT = 2000
MAX_LINE_LENGTH = 2000


def _validate_path(path: str, *, for_write: bool = False) -> Path:
    """Validate and optionally safety-check a filesystem path."""
    p = validate_file_path(path)
    if for_write:
        ok, reason = is_path_safe(str(p), for_write=True)
        if not ok:
            raise ValueError(reason)
    return p


@tool
def read_file(file_path: str, offset: int = 0, limit: int = MAX_LINES_DEFAULT) -> dict:
    """Read contents of a file with line numbers."""
    logger.info("Reading file: %s (offset=%d, limit=%d)", file_path, offset, limit)
    try:
        path = _validate_path(file_path)
    except ValueError as e:
        logger.warning("Path validation failed for %s: %s", file_path, e)
        return {"ok": False, "error": str(e)}

    if not path.exists():
        logger.warning("File not found: %s", file_path)
        return {"ok": False, "error": "File not found", "path": file_path}
    if not path.is_file():
        logger.warning("Not a file: %s", file_path)
        return {"ok": False, "error": "Not a file", "path": file_path}

    settings = get_settings()
    if path.stat().st_size > settings.safety.max_file_size:
        return {"ok": False, "error": "File too large", "path": file_path}

    lines_out = []
    total_read = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for idx, line in enumerate(islice(f, offset, offset + limit), start=offset + 1):
                total_read += 1
                if len(line) > MAX_LINE_LENGTH:
                    line = line[: MAX_LINE_LENGTH - 3] + "..."
                lines_out.append(f"{idx:6}\t{line.rstrip()}" )
    except OSError as e:
        return {"ok": False, "error": f"Error reading file: {e}"}

    if not lines_out:
        return {"ok": True, "content": "(no lines at this offset)", "path": file_path}

    return {
        "ok": True,
        "content": "\n".join(lines_out),
        "path": file_path,
        "offset": offset,
        "lines": total_read,
    }


@tool
def write_file(file_path: str, content: str) -> dict:
    """Write content to a file, creating it if it doesn't exist."""
    logger.info("Writing file: %s (%d bytes)", file_path, len(content))
    try:
        path = _validate_path(file_path, for_write=True)
    except ValueError as e:
        logger.warning("Path validation failed for write %s: %s", file_path, e)
        return {"ok": False, "error": str(e)}

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Successfully wrote %d bytes to %s", len(content), file_path)
        return {"ok": True, "path": file_path, "bytes": len(content)}
    except OSError as e:
        logger.error("Error writing file %s: %s", file_path, e)
        return {"ok": False, "error": f"Error writing file: {e}"}


@tool
def append_file(file_path: str, content: str) -> dict:
    """Append content to a file, creating it if it doesn't exist."""
    logger.info("Appending to file: %s (%d bytes)", file_path, len(content))
    try:
        path = _validate_path(file_path, for_write=True)
    except ValueError as e:
        logger.warning("Path validation failed for append %s: %s", file_path, e)
        return {"ok": False, "error": str(e)}

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
        logger.info("Successfully appended %d bytes to %s", len(content), file_path)
        return {"ok": True, "path": file_path, "bytes": len(content)}
    except OSError as e:
        logger.error("Error appending to file %s: %s", file_path, e)
        return {"ok": False, "error": f"Error appending file: {e}"}


@tool
def edit_file(file_path: str, old_string: str, new_string: str, preview: bool = False) -> dict:
    """Replace a string in a file with a new string."""
    logger.info("Editing file: %s (preview=%s)", file_path, preview)
    logger.debug("Edit: replacing %d chars with %d chars", len(old_string), len(new_string))
    try:
        path = _validate_path(file_path, for_write=True)
    except ValueError as e:
        logger.warning("Path validation failed for edit %s: %s", file_path, e)
        return {"ok": False, "error": str(e)}

    if not path.exists():
        logger.warning("File not found for edit: %s", file_path)
        return {"ok": False, "error": "File not found", "path": file_path}

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.error("Error reading file for edit %s: %s", file_path, e)
        return {"ok": False, "error": f"Error reading file: {e}"}

    count = content.count(old_string)
    if count == 0:
        logger.warning("String not found in %s", file_path)
        return {"ok": False, "error": "String not found"}
    if count > 1:
        logger.warning("String found %d times in %s (must be unique)", count, file_path)
        return {"ok": False, "error": f"String found {count} times"}

    new_content = content.replace(old_string, new_string, 1)

    if preview:
        logger.debug("Preview mode - no changes written")
        return {
            "ok": True,
            "preview": True,
            "before": old_string,
            "after": new_string,
        }

    try:
        path.write_text(new_content, encoding="utf-8")
        logger.info("Successfully edited %s", file_path)
        return {"ok": True, "path": file_path}
    except OSError as e:
        logger.error("Error writing edited file %s: %s", file_path, e)
        return {"ok": False, "error": f"Error writing file: {e}"}


@tool
def list_directory(path: str = ".") -> dict:
    """List contents of a directory."""
    try:
        dir_path = _validate_path(path)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    if not dir_path.exists():
        return {"ok": False, "error": "Directory not found", "path": path}
    if not dir_path.is_dir():
        return {"ok": False, "error": "Not a directory", "path": path}

    try:
        entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as e:
        return {"ok": False, "error": f"Error listing directory: {e}"}

    items = []
    for entry in entries:
        try:
            if entry.is_dir():
                items.append({"type": "dir", "name": entry.name})
            elif entry.is_symlink():
                items.append({"type": "symlink", "name": entry.name})
            else:
                items.append({
                    "type": "file",
                    "name": entry.name,
                    "size": entry.stat().st_size,
                })
        except OSError:
            items.append({"type": "error", "name": entry.name})

    return {"ok": True, "path": str(dir_path), "items": items}


@tool
def read_project_instructions(working_directory: str) -> dict:
    """Read project-specific agent instructions from AGENTS.md.

    Call this at the start of each conversation to load project-specific
    instructions, coding conventions, and rules that must be followed.

    Args:
        working_directory: The project's working directory to check for AGENTS.md
    """
    logger.info("Checking for AGENTS.md in: %s", working_directory)
    agents_path = Path(working_directory) / "AGENTS.md"

    if not agents_path.exists():
        logger.debug("No AGENTS.md found in %s", working_directory)
        return {
            "ok": True,
            "found": False,
            "message": "No AGENTS.md file found. No project-specific instructions to follow.",
        }

    try:
        content = agents_path.read_text(encoding="utf-8", errors="replace")
        logger.info("Loaded AGENTS.md (%d bytes)", len(content))
        return {
            "ok": True,
            "found": True,
            "content": content,
            "message": "Project instructions loaded. Follow these rules for this project.",
        }
    except OSError as e:
        logger.error("Error reading AGENTS.md: %s", e)
        return {"ok": False, "error": f"Error reading AGENTS.md: {e}"}
