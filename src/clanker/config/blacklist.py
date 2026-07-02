"""Command blacklist loading (system-wide + project-specific).

Clanker's sandbox blocks a fixed set of dangerous commands. On top of that,
users can define their own blacklist -- commands the agent must never run --
at two scopes:

* **System-wide**: ``safety.command_blacklist`` in ``~/.clanker/config.yaml``
  (also editable in the ``clanker config`` web UI). Applies to every project.
* **Project-specific**: a plain-text ``.clanker/blacklist`` file inside the
  opened project. One command substring per line; ``#`` comments and blank
  lines are ignored. Committable, so a repo can ship its own bans.

The effective blacklist is the **union** of both -- a project can add bans but
never remove system-wide ones. Matching is a case-insensitive substring test
(handled in :func:`clanker.utils.sandbox.is_command_safe`), mirroring the
built-in ``BLOCKED_COMMANDS`` behaviour.
"""

from __future__ import annotations

import os
from pathlib import Path

from clanker.logging import get_logger

logger = get_logger("blacklist")

# Project-scoped blacklist file, relative to the workspace root.
PROJECT_BLACKLIST_FILE = ".clanker/blacklist"


def load_project_blacklist(working_directory: str | None = None) -> list[str]:
    """Read the project's ``.clanker/blacklist`` file.

    Args:
        working_directory: Workspace root. Defaults to the current directory
            (``execute_shell`` runs from the project cwd).

    Returns:
        Stripped, non-comment, non-blank lines. Never raises -- a missing or
        unreadable file yields an empty list.
    """
    workspace = Path(working_directory or os.getcwd())
    path = workspace / PROJECT_BLACKLIST_FILE

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        logger.warning("Could not read project blacklist %s: %s", path, exc)
        return []

    entries: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        entries.append(stripped)
    return entries


def get_effective_blacklist(working_directory: str | None = None) -> list[str]:
    """Union of the system-wide and project-specific blacklists.

    Args:
        working_directory: Workspace root for the project file. Defaults to the
            current directory.

    Returns:
        De-duplicated list of blacklist entries (system entries first, then any
        additional project entries). Order is stable; matching is
        case-insensitive so exact casing here is not significant.
    """
    # Import lazily to avoid an import cycle (settings -> ... -> blacklist).
    from clanker.config.settings import get_settings

    try:
        system = list(get_settings().safety.command_blacklist)
    except Exception as exc:  # pragma: no cover - defensive; settings misconfig
        logger.warning("Could not read system blacklist from settings: %s", exc)
        system = []

    project = load_project_blacklist(working_directory)

    merged: list[str] = []
    seen: set[str] = set()
    for entry in (*system, *project):
        key = entry.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(entry.strip())
    return merged
