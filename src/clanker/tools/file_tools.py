"""File operation tools for reading, writing, and editing files."""

from pathlib import Path
from itertools import islice

from langchain.tools import tool

from clanker.config import get_settings
from clanker.utils.sandbox import is_path_safe
from clanker.utils.validators import validate_file_path

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
    try:
        path = _validate_path(file_path)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    if not path.exists():
        return {"ok": False, "error": "File not found", "path": file_path}
    if not path.is_file():
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
        return {"ok": True, "content": "(no lines at this offset)"}

    return {
        "ok": True,
        "content": "\n".join(lines_out),
        "offset": offset,
        "lines": total_read,
    }


@tool
def write_file(file_path: str, content: str) -> dict:
    """Write content to a file, creating it if it doesn't exist."""
    try:
        path = _validate_path(file_path, for_write=True)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "path": file_path, "bytes": len(content)}
    except OSError as e:
        return {"ok": False, "error": f"Error writing file: {e}"}


@tool
def append_file(file_path: str, content: str) -> dict:
    """Append content to a file, creating it if it doesn't exist."""
    try:
        path = _validate_path(file_path, for_write=True)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "path": file_path, "bytes": len(content)}
    except OSError as e:
        return {"ok": False, "error": f"Error appending file: {e}"}


@tool
def edit_file(file_path: str, old_string: str, new_string: str, preview: bool = False) -> dict:
    """Replace a string in a file with a new string."""
    try:
        path = _validate_path(file_path, for_write=True)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    if not path.exists():
        return {"ok": False, "error": "File not found", "path": file_path}

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"ok": False, "error": f"Error reading file: {e}"}

    count = content.count(old_string)
    if count == 0:
        return {"ok": False, "error": "String not found"}
    if count > 1:
        return {"ok": False, "error": f"String found {count} times"}

    new_content = content.replace(old_string, new_string, 1)

    if preview:
        return {
            "ok": True,
            "preview": True,
            "before": old_string,
            "after": new_string,
        }

    try:
        path.write_text(new_content, encoding="utf-8")
        return {"ok": True, "path": file_path}
    except OSError as e:
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
