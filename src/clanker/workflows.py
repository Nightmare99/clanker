"""Workflow loading from .clanker/workflows/ directories.

Workflows are markdown files containing stored prompts that can be
executed via the /workflow command.

Workflows are discovered from up to four locations, in this precedence order
(earlier wins on name collision):

* ``<workspace>/.clanker/workflows/`` -- project workflows (committed to the repo)
* ``~/.clanker/workflows/``           -- personal workflows (apply to every project)
* ``<workspace>/.agents/workflows/``  -- project workflows, ``.agents`` fallback
* ``~/.agents/workflows/``            -- personal workflows, ``.agents`` fallback

``.clanker/`` is clanker's own directory and always wins when the same
workflow name exists in both.
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

WorkflowSource = Literal["project", "personal", "project (.agents)", "personal (.agents)"]


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
    """Return the workflow search roots in precedence order (highest first).

    Order: .clanker project, .clanker personal, .agents project (fallback),
    .agents personal (fallback) -- so .clanker always wins a name collision
    against .agents, and project always wins against personal within each.

    Args:
        working_directory: Workspace root. Defaults to current directory.

    Returns:
        List of (directory, source) tuples, highest precedence first.
    """
    workspace = Path(working_directory or os.getcwd())
    return [
        (get_workflows_dir(working_directory), "project"),
        (Path.home() / ".clanker" / WORKFLOWS_DIR, "personal"),
        (workspace / ".agents" / WORKFLOWS_DIR, "project (.agents)"),
        (Path.home() / ".agents" / WORKFLOWS_DIR, "personal (.agents)"),
    ]


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
