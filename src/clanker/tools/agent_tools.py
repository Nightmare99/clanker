"""load_agent tool - lets the model retrieve an agent's configuration on demand.

When the main agent needs to spawn a subagent with a specific role, it calls
load_agent(name) to get the agent's system prompt and tool configuration.
"""

import os

from langchain_core.tools import tool

from clanker.agents import MAX_AGENT_PROMPT_CHARS, list_agents
from clanker.agents import load_agent as _load_agent
from clanker.logging import get_logger

logger = get_logger("tools.agent")


@tool
def load_agent(name: str) -> dict:
    """Load the configuration for an available agent by name.

    Agents are specialized subagents with custom system prompts, defined in
    markdown files under .clanker/agents/. Each agent has a name, description,
    system prompt, and optional tool restrictions.

    Call this tool to retrieve an agent's full configuration before spawning
    it with spawn_subagent.

    Args:
        name: The agent name exactly as shown in the AVAILABLE AGENTS catalog.

    Returns:
        On success: a dict with the agent's system_prompt, tools, and metadata.
        On failure: a dict with ok=False, an error message, and available names.
    """
    agent = _load_agent(name, os.getcwd())

    if agent is None:
        available = sorted(list_agents(os.getcwd()).keys())
        logger.info("load_agent: '%s' not found (available: %s)", name, available)
        return {
            "ok": False,
            "error": f"Agent '{name}' not found.",
            "available": available,
        }

    system_prompt = agent.system_prompt
    if len(system_prompt) > MAX_AGENT_PROMPT_CHARS:
        system_prompt = system_prompt[:MAX_AGENT_PROMPT_CHARS].rstrip() + "\n\n... [agent prompt truncated]"

    logger.info("load_agent: loaded '%s' from %s", agent.name, agent.source)
    return {
        "ok": True,
        "name": agent.name,
        "description": agent.description,
        "system_prompt": system_prompt,
        "tools": agent.tools if agent.tools else "(all default tools)",
        "source": agent.source,
    }
