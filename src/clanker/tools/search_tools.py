"""Search tools for finding files and content."""

import fnmatch
import re
from pathlib import Path

from langchain.tools import tool

from clanker.utils.validators import validate_file_path, validate_glob_pattern

# Limits to prevent runaway searches
MAX_RESULTS = 100
MAX_MATCHES_PER_FILE = 50
MAX_FILE_SIZE = 10_000_000  # 10MB


@tool
def glob_search(pattern: str, path: str = ".") -> str:
    """Find files matching a glob pattern.

    Args:
        pattern: Glob pattern to match (e.g., '**/*.py', 'src/*.ts').
        path: Root directory to search from. Defaults to current directory.

    Returns:
        List of matching file paths, sorted by modification time.
    """
    try:
        pattern = validate_glob_pattern(pattern)
        root = validate_file_path(path)
    except ValueError as e:
        return f"Error: {e}"

    if not root.is_dir():
        return f"Error: Not a directory: {path}"

    try:
        # Use rglob for recursive patterns, glob otherwise
        if "**" in pattern:
            matches = list(root.rglob(pattern.replace("**/", "")))
        else:
            matches = list(root.glob(pattern))
    except OSError as e:
        return f"Error searching: {e}"

    if not matches:
        return f"No files found matching '{pattern}' in {path}"

    # Sort by modification time (newest first)
    try:
        matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        matches.sort(key=lambda p: p.name)

    # Limit results
    truncated = len(matches) > MAX_RESULTS
    matches = matches[:MAX_RESULTS]

    # Format output
    lines = [f"Found {len(matches)} files matching '{pattern}':"]
    for match in matches:
        try:
            rel_path = match.relative_to(root)
        except ValueError:
            rel_path = match
        lines.append(f"  {rel_path}")

    if truncated:
        lines.append(f"\n... (results truncated, showing first {MAX_RESULTS})")

    return "\n".join(lines)


@tool
def grep_search(
    pattern: str,
    path: str = ".",
    file_pattern: str | None = None,
    ignore_case: bool = False,
) -> str:
    """Search file contents using a regular expression.

    Args:
        pattern: Regular expression pattern to search for.
        path: File or directory to search in.
        file_pattern: Optional glob pattern to filter files (e.g., '*.py').
        ignore_case: Whether to perform case-insensitive search.

    Returns:
        Matching lines with file paths and line numbers.
    """
    try:
        search_path = validate_file_path(path)
    except ValueError as e:
        return f"Error: {e}"

    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    results: list[str] = []
    files_searched = 0
    total_matches = 0

    def search_file(file_path: Path) -> list[str]:
        """Search a single file for matches."""
        nonlocal total_matches

        if file_path.stat().st_size > MAX_FILE_SIZE:
            return []

        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            return []

        matches = []
        for line_num, line in enumerate(lines, start=1):
            if regex.search(line):
                # Truncate long lines
                display_line = line.rstrip()
                if len(display_line) > 200:
                    display_line = display_line[:200] + "..."

                matches.append(f"{file_path}:{line_num}: {display_line}")
                total_matches += 1

                if total_matches >= MAX_RESULTS:
                    break

        return matches[:MAX_MATCHES_PER_FILE]

    if search_path.is_file():
        results.extend(search_file(search_path))
        files_searched = 1
    elif search_path.is_dir():
        # Collect files to search
        if file_pattern:
            try:
                file_pattern = validate_glob_pattern(file_pattern)
                if "**" in file_pattern:
                    files = list(search_path.rglob(file_pattern.replace("**/", "")))
                else:
                    files = list(search_path.rglob(file_pattern))
            except ValueError:
                files = list(search_path.rglob("*"))
        else:
            files = [f for f in search_path.rglob("*") if f.is_file()]

        # Filter to text files and search
        for file_path in files:
            if total_matches >= MAX_RESULTS:
                break

            if not file_path.is_file():
                continue

            # Skip binary-looking files
            if _is_likely_binary(file_path):
                continue

            results.extend(search_file(file_path))
            files_searched += 1
    else:
        return f"Error: Path does not exist: {path}"

    if not results:
        return f"No matches found for '{pattern}' in {path}"

    header = f"Found {len(results)} matches in {files_searched} files:\n"
    output = header + "\n".join(results)

    if total_matches >= MAX_RESULTS:
        output += f"\n\n... (showing first {MAX_RESULTS} matches)"

    return output


def _is_likely_binary(path: Path) -> bool:
    """Check if a file is likely binary based on extension and content."""
    binary_extensions = {
        ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe",
        ".zip", ".tar", ".gz", ".bz2", ".xz",
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx",
        ".woff", ".woff2", ".ttf", ".eot",
        ".mp3", ".mp4", ".wav", ".avi", ".mov",
        ".db", ".sqlite", ".sqlite3",
    }

    if path.suffix.lower() in binary_extensions:
        return True

    # Check first few bytes for null characters
    try:
        with open(path, "rb") as f:
            chunk = f.read(1024)
            if b"\x00" in chunk:
                return True
    except OSError:
        return True

    return False
