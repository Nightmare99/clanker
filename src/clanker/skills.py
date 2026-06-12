"""Agent Skills discovery and loading.

Skills are model-discovered capabilities packaged as a directory containing a
``SKILL.md`` file (YAML frontmatter + markdown body) plus optional bundled
files (scripts, templates, data).

Unlike workflows (user-triggered, whole body injected on ``/workflow``), skills
use *progressive disclosure*:

1. A lightweight catalog (each skill's ``name`` + ``description``) is always
   injected into the system prompt, so the model knows what skills exist.
2. When a task matches a skill, the model calls the ``load_skill`` tool to pull
   the full ``SKILL.md`` body into context on demand.
3. The body can reference bundled files; the model reads them with ``read_file``
   and runs scripts with ``execute_shell`` -- no new execution machinery.

Skills are discovered from two locations (project wins on name collision):

* ``<workspace>/.clanker/skills/`` -- project skills (committed to the repo)
* ``~/.clanker/skills/``           -- personal skills (apply to every project)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from clanker.logging import get_logger

logger = get_logger("skills")

SKILLS_DIR = "skills"
SKILL_FILE = "SKILL.md"

# Each description is truncated to this many characters in the always-on catalog
# so a verbose skill can't bloat every system prompt.
MAX_DESC_CHARS = 500

# Guard on the full body returned by load_skill / force-loaded via /skill.
MAX_SKILL_BODY_CHARS = 10_000

SKILL_PREAMBLE = (
    "Below are the full instructions for a skill. Follow them to complete the "
    "user's request. The skill may reference bundled files in its directory -- "
    "read them with read_file and run scripts with execute_shell.\n\n"
)

SkillSource = Literal["project", "personal"]


@dataclass
class Skill:
    """A discovered skill.

    Attributes:
        name: Canonical skill id (frontmatter ``name``, falls back to dir name).
        description: Trigger signal -- what the skill does and when to use it.
        body: The markdown body of SKILL.md (instructions), loaded on demand.
        directory: Absolute path to the skill's directory (where bundled files live).
        source: "project" (.clanker/skills) or "personal" (~/.clanker/skills).
    """

    name: str
    description: str
    body: str
    directory: Path
    source: SkillSource


def get_skill_dirs(working_directory: str | None = None) -> list[tuple[Path, SkillSource]]:
    """Return the skill search roots in precedence order (project first).

    Args:
        working_directory: Workspace root. Defaults to current directory.

    Returns:
        List of (directory, source) tuples. Project dir is listed first so it
        takes precedence over personal on name collision.
    """
    workspace = Path(working_directory or os.getcwd())
    project = workspace / ".clanker" / SKILLS_DIR
    personal = Path.home() / ".clanker" / SKILLS_DIR
    return [(project, "project"), (personal, "personal")]


def parse_skill_md(path: Path) -> tuple[dict, str] | None:
    """Parse a SKILL.md file into (frontmatter_dict, body).

    Expects YAML frontmatter delimited by leading ``---`` lines:

        ---
        name: my-skill
        description: ...
        ---
        <markdown body>

    Returns None (and logs) on any read/parse failure or if frontmatter is
    missing or not a mapping -- discovery must never crash on a bad skill.

    Args:
        path: Path to a SKILL.md file.

    Returns:
        (metadata, body) tuple, or None if the file can't be parsed.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Could not read skill file %s: %s", path, e)
        return None

    lines = text.splitlines()
    # Skip leading blank lines, then require an opening '---' delimiter line.
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start >= len(lines) or lines[start].strip() != "---":
        logger.warning("Skill %s has no YAML frontmatter; skipping", path)
        return None

    # Find the closing '---' delimiter line.
    close = None
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == "---":
            close = i
            break
    if close is None:
        logger.warning("Skill %s has unterminated frontmatter; skipping", path)
        return None

    frontmatter_raw = "\n".join(lines[start + 1 : close])
    body = "\n".join(lines[close + 1 :]).strip()

    try:
        meta = yaml.safe_load(frontmatter_raw)
    except yaml.YAMLError as e:
        logger.warning("Skill %s has malformed frontmatter YAML: %s", path, e)
        return None

    if not isinstance(meta, dict):
        logger.warning("Skill %s frontmatter is not a mapping; skipping", path)
        return None

    return meta, body


def _load_skill_from_dir(skill_dir: Path, source: SkillSource) -> Skill | None:
    """Build a Skill from a directory, or None if it isn't a valid skill."""
    skill_file = skill_dir / SKILL_FILE
    if not skill_file.is_file():
        return None

    parsed = parse_skill_md(skill_file)
    if parsed is None:
        return None

    meta, body = parsed
    name = meta.get("name") or skill_dir.name
    description = meta.get("description")

    if not isinstance(name, str) or not name.strip():
        logger.warning("Skill %s has invalid 'name'; skipping", skill_file)
        return None
    if not isinstance(description, str) or not description.strip():
        logger.warning("Skill %s missing required 'description'; skipping", skill_file)
        return None

    return Skill(
        name=name.strip(),
        description=description.strip(),
        body=body,
        directory=skill_dir.resolve(),
        source=source,
    )


def list_skills(working_directory: str | None = None) -> dict[str, Skill]:
    """Discover all skills from project and personal directories.

    Project skills take precedence over personal skills with the same name.

    Args:
        working_directory: Workspace root. Defaults to current directory.

    Returns:
        Mapping of skill name -> Skill, with project entries winning collisions.
    """
    skills: dict[str, Skill] = {}

    # Iterate personal first, then project, so project overwrites personal.
    for directory, source in reversed(get_skill_dirs(working_directory)):
        if not directory.is_dir():
            continue
        for entry in sorted(directory.iterdir()):
            if not entry.is_dir():
                continue
            skill = _load_skill_from_dir(entry, source)
            if skill is None:
                continue
            if skill.name in skills and source == "personal":
                # Project already claimed this name; don't let personal override.
                continue
            skills[skill.name] = skill

    return dict(sorted(skills.items()))


def load_skill(name: str, working_directory: str | None = None) -> Skill | None:
    """Load a single skill by name.

    Args:
        name: Skill name (case-insensitive match).
        working_directory: Workspace root. Defaults to current directory.

    Returns:
        The Skill, or None if not found.
    """
    skills = list_skills(working_directory)
    if name in skills:
        return skills[name]
    # Case-insensitive fallback.
    lowered = name.strip().lower()
    for skill_name, skill in skills.items():
        if skill_name.lower() == lowered:
            return skill
    return None


def get_skills_catalog(working_directory: str | None = None) -> str:
    """Build the always-on skills catalog for the system prompt.

    One line per skill: ``- name: description (source)``. Descriptions are
    truncated to MAX_DESC_CHARS to bound prompt cost.

    Args:
        working_directory: Workspace root. Defaults to current directory.

    Returns:
        Formatted catalog string, or empty string if no skills exist.
    """
    skills = list_skills(working_directory)
    if not skills:
        return ""

    lines: list[str] = []
    for skill in skills.values():
        desc = skill.description
        if len(desc) > MAX_DESC_CHARS:
            desc = desc[:MAX_DESC_CHARS].rstrip() + "..."
        lines.append(f"- {skill.name}: {desc} ({skill.source})")

    return "\n".join(lines)
