"""Subagent spawning tool that uses configured agents from .clanker/agents/."""

import asyncio
import os
import threading
import uuid
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage

from clanker.agents import load_agent as load_agent_config
from clanker.config import get_settings
from clanker.logging import get_logger

logger = get_logger("tools.subagent")


def _resolve_tools(tool_names: list[str]) -> list:
    """Resolve a list of tool name strings to actual tool objects."""
    from clanker.tools import get_tools

    if not tool_names:
        return get_tools()

    all_tools = get_tools()
    tool_map = {t.name.lower(): t for t in all_tools}

    resolved = []
    for name in tool_names:
        matched = tool_map.get(name.lower())
        if matched:
            resolved.append(matched)
        else:
            logger.warning("spawn_subagent: tool '%s' not found, skipping", name)
    return resolved


@tool
async def spawn_subagent(agent_name: str, prompt: str) -> dict:
    """Spawn a configured subagent to handle a subtask in a separate thread.

    The subagent runs in its own thread with its own event loop so it is
    completely isolated from the parent's streaming state — no shared
    spinners, no shared event loop, no duplicate output.

    The subagent's full output is streamed live to the user terminal. The
    return value contains only a brief summary — do NOT repeat the full
    output in your response to the user. Use the summary to know what the
    subagent found.

    Args:
        agent_name: Name of the agent to spawn (must match an agent from
                    AVAILABLE AGENTS catalog).
        prompt: Detailed instructions for the subagent specifying what it needs to do.

    Returns:
        A dictionary with a brief summary of the subagent's findings, plus
        execution status and token usage. The full output was already shown
        to the user during the subagent run.
    """
    logger.info("Spawning subagent '%s' with prompt: %s...", agent_name, prompt[:80])

    from clanker.ui.streaming import (
        stream_agent_response_async,
        get_active_console,
        _current_loading_live,
    )
    from clanker.ui.console import Console

    # Resolve agent configuration
    agent_config = load_agent_config(agent_name, os.getcwd())
    if agent_config is None:
        from clanker.agents import list_agents
        available = sorted(list_agents(os.getcwd()).keys())
        return {
            "success": False,
            "error": f"Agent '{agent_name}' not found. Available agents: {available}",
        }

    settings = get_settings()
    parent_console = get_active_console()

    # Stop the parent's loading spinner so the subagent owns the terminal
    # without two Rich Live displays fighting for the same area.
    parent_spinner_stopped = False
    if _current_loading_live is not None:
        try:
            _current_loading_live.stop()
            parent_spinner_stopped = True
        except Exception:
            pass

    # Print visual start boundary on the parent console
    parent_console._console.print()
    parent_console._console.print(
        f"[dim]┌─ Agent '{agent_name}' started[/dim]",
    )

    # Create a separate Console for the subagent that writes to the same
    # terminal file descriptor. This gives the subagent its own Rich console
    # so its Live/spinner doesn't conflict with the parent's.
    sub_console = Console(agent_label=agent_name)
    sub_console._console.file = parent_console._console.file

    # Resolve tools for this agent
    agent_tools = _resolve_tools(agent_config.tools)

    # Prepare subagent state and config
    config = {
        "configurable": {
            "thread_id": f"subagent-{uuid.uuid4().hex[:8]}"
        },
    }
    state = {
        "messages": [HumanMessage(content=prompt)],
        "working_directory": os.getcwd(),
    }

    result_container: list = []
    error_container: list = []

    def run_subagent() -> None:
        """Run the subagent in this thread's own fresh event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                stream_agent_response_async(
                    settings=settings,
                    checkpointer=None,
                    state=state,
                    config=config,
                    console=sub_console,
                    tools=agent_tools,
                    system_prompt=agent_config.system_prompt,
                )
            )
            result_container.append(result)
        except Exception as e:
            error_container.append(e)
        finally:
            loop.close()

    def make_summary(text: str, max_len: int = 300) -> str:
        """Truncate subagent response to a brief summary for the parent agent.

        The full response is already streamed to the user terminal. The parent
        agent only needs a short summary so it doesn't repeat everything.
        Returns a self-contained block so the parent does not continue it.
        """
        text = text.strip()
        if len(text) <= max_len:
            return text
        # Find a reasonable break point (end of a sentence or paragraph)
        truncated = text[:max_len]
        last_newline = truncated.rfind("\n\n")
        last_period = truncated.rfind(". ")
        if last_newline > max_len * 0.5:
            return truncated[:last_newline]
        if last_period > max_len * 0.5:
            return truncated[:last_period + 1]
        return truncated.rsplit(None, 1)[0]

    # Run in a dedicated thread — completely isolated from parent's event loop
    t = threading.Thread(target=run_subagent, daemon=True)
    t.start()
    t.join()

    # Restart the parent's loading spinner (it was stopped before spawn)
    if parent_spinner_stopped:
        try:
            _current_loading_live.start()
        except Exception:
            pass

    # Print visual end boundary
    parent_console._console.print(
        f"[dim]└─ Agent '{agent_name}' completed[/dim]",
    )
    parent_console._console.print()

    if error_container:
        return {
            "success": False,
            "agent": agent_name,
            "error": str(error_container[0]),
        }

    result = result_container[0]
    summary = make_summary(result.response)
    return {
        "success": True,
        "agent": agent_name,
        "summary": f"[Subagent output already shown above. Summary: {summary}]",
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }
