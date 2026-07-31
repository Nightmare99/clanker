"""Workflow loading from .clanker/workflows/ directories.

Workflows are markdown files containing stored prompts that can be
executed via the /workflow command.

Workflows are discovered from two locations (project wins on name collision):

* ``<workspace>/.clanker/workflows/`` -- project workflows (committed to the repo)
* ``~/.clanker/workflows/``           -- personal workflows (apply to every project)
"""

import os
from pathlib import Path
from typing import Literal

WORKFLOWS_DIR = "workflows"
MAX_WORKFLOW_CHARS = 1500

WORKFLOW_PREAMBLE = (
    "Below is a workflow containing a series of instructions to be executed sequentially. "
    "Complete each step thoroughly before moving to the next.\n\n"
)

WorkflowSource = Literal["project", "personal"]


def get_workflows_dir(working_directory: str | None = None) -> Path:
    """Get the project workflows directory path.

    Args:
        working_directory: Workspace root. Defaults to current directory.

    Returns:
        Path to .clanker/workflows/ directory.
    """
    workspace = Path(working_directory or os.getcwd())
    return workspace / ".clanker" / WORKFLOWS_DIR


def get_workflow_dirs(working_directory: str | None = None) -> list[tuple[Path, WorkflowSource]]:
    """Return the workflow search roots in precedence order (project first).

    Args:
        working_directory: Workspace root. Defaults to current directory.

    Returns:
        List of (directory, source) tuples. Project dir is listed first so it
        takes precedence over personal on name collision.
    """
    personal = Path.home() / ".clanker" / WORKFLOWS_DIR
    return [(get_workflows_dir(working_directory), "project"), (personal, "personal")]


def list_workflows(working_directory: str | None = None) -> list[str]:
    """List available workflow names (without .md extension).

    Merges project and personal workflows; a project workflow shadows a
    personal one with the same name.

    Args:
        working_directory: Workspace root. Defaults to current directory.

    Returns:
        Sorted list of workflow names.
    """
    names: set[str] = set()
    for directory, _source in get_workflow_dirs(working_directory):
        if not directory.is_dir():
            continue
        for f in directory.iterdir():
            if f.is_file() and f.suffix == ".md":
                names.add(f.stem)

    return sorted(names)


def load_workflow(name: str, working_directory: str | None = None) -> str | None:
    """Load a workflow's content by name.

    Checks the project workflows directory first, then falls back to the
    personal (global) directory.

    Args:
        name: Workflow name (without .md extension).
        working_directory: Workspace root. Defaults to current directory.

    Returns:
        Workflow content string, or None if not found.
    """
    for directory, _source in get_workflow_dirs(working_directory):
        workflow_path = directory / f"{name}.md"
        if not workflow_path.is_file():
            continue
        try:
            return workflow_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None

    return None
