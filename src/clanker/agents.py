"""Configurable agents discovery and loading.

Agents are specialized LLM configurations defined as markdown files with YAML
frontmatter under `.clanker/agents/`. Each agent file defines a custom system
prompt and metadata that the main agent can use when spawning subagents.

Unlike skills (which provide step-by-step instructions the main agent follows),
agents define independent subagents with their own system prompts, tool access,
and behavior. The main agent spawns an agent to delegate a subtask.

Agent files follow this format:

    ---
    name: code-reviewer
    description: Specialized agent for reviewing code quality and suggesting improvements.
    tools: [read_file, grep_search, glob_search]
    model: claude-haiku  # optional; uses session default if omitted
    ---
    # Code Reviewer

    You are an expert code reviewer. Your job is to ...

The `model` field is optional. When specified, the agent uses the named model
(must match a model configured in `~/.clanker/models.json`). If omitted, the
agent uses the session's default model.

Agents are discovered from two locations (project wins on name collision):

* `<workspace>/.clanker/agents/` -- project agents (committed to the repo)
* `~/.clanker/agents/`           -- personal agents (apply to every project)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from clanker.logging import get_logger

logger = get_logger("agents")

AGENTS_DIR = "agents"
AGENT_FILE_EXT = ".md"

# Each description is truncated to this many characters in the always-on catalog
MAX_DESC_CHARS = 500

# Guard on the full system prompt returned by load_agent.
MAX_AGENT_PROMPT_CHARS = 15_000

AgentSource = Literal["project", "personal"]


@dataclass
class Agent:
    """A discovered agent configuration.

    Attributes:
        name: Canonical agent id (frontmatter name, falls back to filename).
        description: What the agent does and when to use it.
        system_prompt: The full markdown body serving as the agent's system prompt.
        tools: Optional list of tool names the agent should have access to.
               If empty/missing, the agent gets all default tools.
        model: Optional model name to use for this agent. If omitted, the
               session's default model is used. The name must match a model
               configured in ~/.clanker/models.json.
        directory: Absolute path to the agent's directory.
        source: "project" (.clanker/agents) or "personal" (~/.clanker/agents).
    """

    name: str
    description: str
    system_prompt: str
    tools: list[str]
    directory: Path
    source: AgentSource
    model: str | None = None


def get_agent_dirs(working_directory: str | None = None) -> list[tuple[Path, AgentSource]]:
    """Return the agent search roots in precedence order (project first)."""
    workspace = Path(working_directory or os.getcwd())
    project = workspace / ".clanker" / AGENTS_DIR
    personal = Path.home() / ".clanker" / AGENTS_DIR
    return [(project, "project"), (personal, "personal")]


def parse_agent_md(path: Path) -> tuple[dict, str] | None:
    """Parse an agent markdown file into (frontmatter_dict, body).

    Expects YAML frontmatter delimited by leading `---` lines:

        ---
        name: my-agent
        description: Does X and Y.
        tools: [read_file, grep_search]
        ---
        <markdown system prompt>

    Returns None on any read/parse failure.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Could not read agent file %s: %s", path, e)
        return None

    lines = text.splitlines()
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start >= len(lines) or lines[start].strip() != "---":
        logger.warning("Agent %s has no YAML frontmatter; skipping", path)
        return None

    close = None
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == "---":
            close = i
            break
    if close is None:
        logger.warning("Agent %s has unterminated frontmatter; skipping", path)
        return None

    frontmatter_raw = "\n".join(lines[start + 1 : close])
    body = "\n".join(lines[close + 1 :]).strip()

    try:
        meta = yaml.safe_load(frontmatter_raw)
    except yaml.YAMLError as e:
        logger.warning("Agent %s has malformed frontmatter YAML: %s", path, e)
        return None

    if not isinstance(meta, dict):
        logger.warning("Agent %s frontmatter is not a mapping; skipping", path)
        return None

    return meta, body


def _load_agent_from_file(agent_file: Path, source: AgentSource) -> Agent | None:
    """Build an Agent from a markdown file, or None if invalid."""
    parsed = parse_agent_md(agent_file)
    if parsed is None:
        return None

    meta, body = parsed
    name = meta.get("name") or agent_file.stem
    description = meta.get("description", "")
    tools = meta.get("tools", [])
    model = meta.get("model", None)

    if not isinstance(name, str) or not name.strip():
        logger.warning("Agent %s has invalid 'name'; skipping", agent_file)
        return None
    if not isinstance(description, str) or not description.strip():
        logger.warning("Agent %s missing required 'description'; skipping", agent_file)
        return None
    if not body.strip():
        logger.warning("Agent %s has empty system prompt body; skipping", agent_file)
        return None
    if not isinstance(tools, list):
        logger.warning("Agent %s has invalid 'tools'; defaulting to all tools", agent_file)
        tools = []

    # model is optional; if provided, validate it's a non-empty string
    agent_model: str | None = None
    if model is not None:
        if isinstance(model, str) and model.strip():
            agent_model = model.strip()
        else:
            logger.warning("Agent %s has invalid 'model'; ignoring", agent_file)

    return Agent(
        name=name.strip(),
        description=description.strip(),
        system_prompt=body.strip(),
        tools=[t.strip() for t in tools if isinstance(t, str) and t.strip()],
        model=agent_model,
        directory=agent_file.parent.resolve(),
        source=source,
    )


def list_agents(working_directory: str | None = None) -> dict[str, Agent]:
    """Discover all agents from project and personal directories.

    Project agents take precedence over personal agents with the same name.
    """
    agents: dict[str, Agent] = {}

    for directory, source in reversed(get_agent_dirs(working_directory)):
        if not directory.is_dir():
            continue
        for entry in sorted(directory.iterdir()):
            if not entry.is_file() or entry.suffix.lower() != AGENT_FILE_EXT:
                continue
            agent = _load_agent_from_file(entry, source)
            if agent is None:
                continue
            if agent.name in agents and source == "personal":
                continue
            agents[agent.name] = agent

    return dict(sorted(agents.items()))


def load_agent(name: str, working_directory: str | None = None) -> Agent | None:
    """Load a single agent by name."""
    agents = list_agents(working_directory)
    if name in agents:
        return agents[name]
    lowered = name.strip().lower()
    for agent_name, agent in agents.items():
        if agent_name.lower() == lowered:
            return agent
    return None


def list_personal_agents() -> dict[str, Agent]:
    """Discover agents from ``~/.clanker/agents/`` only, ignoring project agents.

    Used by the global config UI, which edits the user-level agent set and has
    no project working-directory context to resolve project agents against.
    """
    personal_dir = Path.home() / ".clanker" / AGENTS_DIR
    agents: dict[str, Agent] = {}
    if not personal_dir.is_dir():
        return agents

    for entry in sorted(personal_dir.iterdir()):
        if not entry.is_file() or entry.suffix.lower() != AGENT_FILE_EXT:
            continue
        agent = _load_agent_from_file(entry, "personal")
        if agent is None:
            continue
        agents[agent.name] = agent

    return dict(sorted(agents.items()))


def set_agent_model(name: str, model: str | None) -> bool:
    """Set (or clear, if ``model`` is falsy) the ``model`` field on a personal agent.

    Only ``~/.clanker/agents/`` is searched -- this never touches project
    agents, matching ``list_personal_agents``. Rewrites just the frontmatter,
    preserving the rest of the file's fields and the system-prompt body.

    Returns:
        True if a matching personal agent file was found and updated, False
        if no personal agent has that name.
    """
    personal_dir = Path.home() / ".clanker" / AGENTS_DIR
    if not personal_dir.is_dir():
        return False

    lowered = name.strip().lower()
    target: Path | None = None
    for entry in sorted(personal_dir.iterdir()):
        if not entry.is_file() or entry.suffix.lower() != AGENT_FILE_EXT:
            continue
        parsed = parse_agent_md(entry)
        if parsed is None:
            continue
        meta, _ = parsed
        entry_name = meta.get("name") or entry.stem
        if isinstance(entry_name, str) and entry_name.strip().lower() == lowered:
            target = entry
            break

    if target is None:
        return False

    parsed = parse_agent_md(target)
    if parsed is None:
        return False
    meta, body = parsed

    if model:
        meta["model"] = model
    else:
        meta.pop("model", None)

    new_frontmatter = yaml.safe_dump(meta, sort_keys=False, default_flow_style=False).strip()
    target.write_text(f"---\n{new_frontmatter}\n---\n\n{body}\n", encoding="utf-8")
    return True


def get_agents_catalog(working_directory: str | None = None) -> str:
    """Build the always-on agents catalog for the system prompt.

    One line per agent: `- name: description (source)`.
    """
    agents = list_agents(working_directory)
    if not agents:
        return ""

    lines: list[str] = []
    for agent in agents.values():
        desc = agent.description
        if len(desc) > MAX_DESC_CHARS:
            desc = desc[:MAX_DESC_CHARS].rstrip() + "..."
        model_tag = f" [model: {agent.model}]" if agent.model else ""
        lines.append(f"- {agent.name}: {desc} ({agent.source}{model_tag})")

    return "\n".join(lines)
