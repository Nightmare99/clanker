"""load_skill tool - lets the model pull a skill's full instructions on demand.

This is the model-triggered half of progressive disclosure: the system prompt
advertises a lightweight catalog of skill names + descriptions, and when a task
matches, the model calls load_skill(name) to bring the full SKILL.md body into
context along with the skill's directory path (so it can read bundled files with
read_file and run bundled scripts with execute_shell).
"""

import os

from langchain_core.tools import tool

from clanker.logging import get_logger
from clanker.skills import MAX_SKILL_BODY_CHARS, list_skills
from clanker.skills import load_skill as _load_skill

logger = get_logger("tools.skill")


@tool
def load_skill(name: str) -> dict:
    """Load the full instructions for an available skill by name.

    Skills are specialized capabilities advertised in the AVAILABLE SKILLS
    section of your system prompt (each with a name and description). When a
    user request matches a skill's description, call this tool FIRST to retrieve
    the skill's complete step-by-step instructions before acting.

    The returned instructions may reference bundled files (scripts, templates,
    data) that live in the skill's directory. Use the returned `skill_directory`
    path to locate them: read files with `read_file` and run scripts with
    `execute_shell`.

    Args:
        name: The skill name exactly as shown in the AVAILABLE SKILLS catalog.

    Returns:
        On success: a dict with the skill's instructions, its directory path,
        and a usage note. On failure: a dict with ok=False, an error message,
        and the list of available skill names.
    """
    skill = _load_skill(name, os.getcwd())

    if skill is None:
        available = sorted(list_skills(os.getcwd()).keys())
        logger.info("load_skill: '%s' not found (available: %s)", name, available)
        return {
            "ok": False,
            "error": f"Skill '{name}' not found.",
            "available": available,
        }

    body = skill.body
    if len(body) > MAX_SKILL_BODY_CHARS:
        body = body[:MAX_SKILL_BODY_CHARS].rstrip() + "\n\n... [skill instructions truncated]"

    logger.info("load_skill: loaded '%s' from %s", skill.name, skill.directory)
    return {
        "ok": True,
        "name": skill.name,
        "instructions": body,
        "skill_directory": str(skill.directory),
        "note": (
            "Follow these instructions. Bundled files live in skill_directory: "
            "read them with read_file and run scripts with execute_shell."
        ),
    }
