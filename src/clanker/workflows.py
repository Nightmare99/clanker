"""Workflow loading from .clanker/workflows/ directory.

Workflows are markdown files containing stored prompts that can be
executed via the /workflow command.
"""

import os
from pathlib import Path


WORKFLOWS_DIR = "workflows"


def get_workflows_dir(working_directory: str | None = None) -> Path:
    """Get the workflows directory path.

    Args:
        working_directory: Workspace root. Defaults to current directory.

    Returns:
        Path to .clanker/workflows/ directory.
    """
    workspace = Path(working_directory or os.getcwd())
    return workspace / ".clanker" / WORKFLOWS_DIR


def list_workflows(working_directory: str | None = None) -> list[str]:
    """List available workflow names (without .md extension).

    Args:
        working_directory: Workspace root. Defaults to current directory.

    Returns:
        Sorted list of workflow names.
    """
    workflows_dir = get_workflows_dir(working_directory)
    if not workflows_dir.is_dir():
        return []

    names = []
    for f in workflows_dir.iterdir():
        if f.is_file() and f.suffix == ".md":
            names.append(f.stem)

    return sorted(names)


def load_workflow(name: str, working_directory: str | None = None) -> str | None:
    """Load a workflow's content by name.

    Args:
        name: Workflow name (without .md extension).
        working_directory: Workspace root. Defaults to current directory.

    Returns:
        Workflow content string, or None if not found.
    """
    workflows_dir = get_workflows_dir(working_directory)
    workflow_path = workflows_dir / f"{name}.md"

    if not workflow_path.is_file():
        return None

    try:
        return workflow_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
