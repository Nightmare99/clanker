"""Subagent spawning tool that uses configured agents from .clanker/agents/."""

import asyncio
import contextlib
import os
import queue
import threading
import uuid

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

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
    completely isolated from the parent's streaming state.

    The subagent's progress is streamed live to the parent UI as a single
    updating tool row showing the current action.

    Args:
        agent_name: Name of the agent to spawn (must match an agent from
                    AVAILABLE AGENTS catalog).
        prompt: Detailed instructions for the subagent specifying what it needs to do.

    Returns:
        A dictionary with a brief summary of the subagent's findings, plus
        execution status and token usage.
    """
    logger.info("Spawning subagent '%s' with prompt: %s...", agent_name, prompt[:80])

    from clanker.ui.console import Console
    from clanker.ui.streaming import (
        _current_loading_live,
        get_active_console,
        stream_agent_response_async,
    )

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

    # Stop the parent's loading spinner
    parent_spinner_stopped = False
    if _current_loading_live is not None:
        try:
            _current_loading_live.stop()
            parent_spinner_stopped = True
        except Exception:
            pass

    # Create a separate Console for the subagent — no TUI widget access
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

    # Thread-safe queue for progress updates from subagent thread
    _thread_queue: queue.Queue = queue.Queue()

    def _progress_callback(action_type: str, tool_name: str, arg_str: str, tool_output: str = "") -> None:
        """Called from subagent's streaming thread to report progress."""
        try:
            _thread_queue.put_nowait((action_type, tool_name, arg_str))
        except Exception:
            pass

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
                    progress_callback=_progress_callback,
                )
            )
            result_container.append(result)
        except Exception as e:
            error_container.append(e)
        finally:
            _thread_queue.put_nowait(("done", "", ""))
            loop.close()

    # Start subagent in a dedicated thread
    t = threading.Thread(target=run_subagent, daemon=True)
    t.start()

    # Create the spawn_subagent tool entry in the parent TUI — use agent name
    textual_app = getattr(parent_console, "_textual_app", None)
    tool_entry = None
    if textual_app:
        try:
            chat_log = textual_app.get_chat_log()
            tool_entry = chat_log.add_tool_start(
                agent_name,
                "Starting...",
            )
        except Exception:
            tool_entry = None

    # Drain progress queue without blocking the event loop
    current_action = "Starting..."
    last_update_time = 0.0
    _UPDATE_INTERVAL = 0.5  # seconds between TUI updates

    import time
    while True:
        # Check if thread is done and queue is drained
        if not t.is_alive() and _thread_queue.empty():
            break

        # Drain all available items from the queue, keeping only the latest
        # "start" entry (most informative — shows [tool_name] args)
        latest_action = None
        try:
            while True:
                item = _thread_queue.get_nowait()
                action_type, tool_name, arg_str = item
                if action_type == "start":
                    latest_action = f"[{tool_name}] {arg_str}" if arg_str else f"[{tool_name}]"
        except queue.Empty:
            pass

        # Only update TUI if action changed and enough time has passed
        if latest_action and latest_action != current_action:
            now = time.monotonic()
            if now - last_update_time >= _UPDATE_INTERVAL:
                current_action = latest_action
                last_update_time = now
                if tool_entry and textual_app:
                    try:
                        chat_log = textual_app.get_chat_log()
                        chat_log.update_tool_progress(tool_entry, current_action)
                    except Exception:
                        pass

        # Yield to event loop to keep TUI responsive
        await asyncio.sleep(0.1)

    # Restart the parent's loading spinner
    if parent_spinner_stopped:
        with contextlib.suppress(Exception):
            _current_loading_live.start()

    # Finalize the tool entry
    if error_container:
        error_msg = str(error_container[0])
        if tool_entry and textual_app:
            try:
                chat_log = textual_app.get_chat_log()
                chat_log.finalize_subagent(
                    tool_entry, agent_name, f"Error: {error_msg}", success=False
                )
            except Exception:
                pass
        return {
            "success": False,
            "agent": agent_name,
            "error": error_msg,
        }

    result = result_container[0]

    def make_summary(text: str, max_len: int = 300) -> str:
        """Truncate subagent response to a brief summary for the parent agent."""
        text = text.strip()
        if len(text) <= max_len:
            return text
        truncated = text[:max_len]
        last_newline = truncated.rfind("\n\n")
        last_period = truncated.rfind(". ")
        if last_newline > max_len * 0.5:
            return truncated[:last_newline]
        if last_period > max_len * 0.5:
            return truncated[:last_period + 1]
        return truncated.rsplit(None, 1)[0]

    summary = make_summary(result.response)

    # Use cumulative tokens (subagent may have multiple model calls)
    sub_input_tokens = result.cumulative_input_tokens or result.input_tokens
    sub_output_tokens = result.cumulative_output_tokens or result.output_tokens
    sub_cache_read = result.cumulative_cache_read_tokens or result.cache_read_tokens
    sub_cache_creation = result.cumulative_cache_creation_tokens or result.cache_creation_tokens

    # Add subagent tokens/cost to the parent session tracker
    if textual_app and hasattr(textual_app, "add_subagent_tokens"):
        try:
            textual_app.add_subagent_tokens(
                sub_input_tokens,
                sub_output_tokens,
                sub_cache_read,
                sub_cache_creation,
            )
        except Exception:
            pass

    # Compute cost from the model config
    cost_usd: float | None = None
    try:
        from clanker.config import get_default_model
        cm = get_default_model()
        if cm:
            cost_usd = cm.compute_cost(
                sub_input_tokens,
                sub_output_tokens,
                sub_cache_read,
                sub_cache_creation,
            )
    except Exception:
        pass

    # Finalize TUI: full markdown output + token/cost line
    if tool_entry and textual_app:
        try:
            chat_log = textual_app.get_chat_log()
            chat_log.finalize_subagent(
                tool_entry,
                agent_name,
                result.response,
                input_tokens=sub_input_tokens,
                output_tokens=sub_output_tokens,
                cost_usd=cost_usd,
                success=True,
            )
        except Exception:
            pass

    return {
        "success": True,
        "agent": agent_name,
        "summary": f"[Subagent output already shown above. Summary: {summary}]",
        "input_tokens": sub_input_tokens,
        "output_tokens": sub_output_tokens,
    }
