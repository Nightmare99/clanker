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

# Appended to every subagent system prompt so that output stays concise.
# The full response is sent to the parent agent (not shown directly in TUI),
# so subagents should keep output brief to avoid flooding the parent context.
# Maximum word count for subagent output sent to the parent agent.
# If the subagent's response exceeds this, the full output is written to a
# temporary file and a truncated summary + file path reference is returned.
# This is a hard ceiling — the LLM may ignore the conciseness instructions in
# the system prompt, so we enforce it programmatically.
_SUBAGENT_MAX_WORDS = 800

# Maximum word count for subagent output sent to the parent agent.
# If the subagent's response exceeds this, the full output is written to a
# temporary file and a truncated summary + file path reference is returned.
# This is a hard ceiling — the LLM may ignore the conciseness instructions in
# the system prompt, so we enforce it programmatically.
_SUBAGENT_MAX_WORDS = 800

_SUBAGENT_CONCISE_INSTRUCTIONS = """

## Output conciseness

You are running as a subagent — your full output is sent to a parent agent that
will relay it to the user. Keep your final response to **500-700 words** so it
doesn't flood the parent agent's context. If your findings exceed that:

1. Write the detailed output to a temporary file (e.g.,
   `/tmp/clanker_<agent>_<timestamp>.md`)
2. In your response, summarize the key findings and reference the file path so
   the parent agent can read the full details if needed."""


def _build_subagent_system_prompt(base_prompt: str) -> str:
    """Combine the agent's base system prompt with conciseness instructions."""
    return base_prompt + _SUBAGENT_CONCISE_INSTRUCTIONS


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
    from clanker.ui.subagent_history import SubagentRun, SubagentToolCall

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
    textual_app = getattr(parent_console, "_textual_app", None)

    run_record = SubagentRun(agent_name=agent_name, prompt=prompt)
    if textual_app is not None:
        with contextlib.suppress(Exception):
            textual_app.register_subagent_run(run_record)

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

    def _progress_callback(
        action_type: str,
        tool_name: str,
        arg_str: str,
        tool_output: str = "",
        tool_input: dict | None = None,
    ) -> None:
        """Called from subagent's streaming thread to report progress."""
        try:
            _thread_queue.put_nowait((action_type, tool_name, arg_str, tool_output, tool_input))
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
                    system_prompt=_build_subagent_system_prompt(agent_config.system_prompt),
                    progress_callback=_progress_callback,
                    model_name=agent_config.model,
                )
            )
            result_container.append(result)
        except Exception as e:
            import traceback
            logger.error(
                "Subagent '%s' thread failed: %s\n%s",
                agent_name, e, traceback.format_exc(),
            )
            error_container.append(e)
        finally:
            _thread_queue.put_nowait(("done", "", "", "", None))
            # Cancel any pending tasks (debounce timers, etc.) before closing
            # the loop to avoid "Event loop is closed" errors when multiple
            # subagents run in parallel.
            try:
                pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                loop.close()
            except Exception:
                try:
                    loop.close()
                except Exception:
                    pass

    # Start subagent in a dedicated thread
    t = threading.Thread(target=run_subagent, daemon=True)
    t.start()

    # Create the spawn_subagent tool entry in the parent TUI — use agent name
    tool_entry = None
    if textual_app:
        try:
            # We're already on the TUI's event loop thread (spawn_subagent runs
            # as a tool call within the parent's streaming context), so call the
            # widget methods directly. call_from_thread would fail with
            # RuntimeError because it requires a different thread.
            tool_entry = textual_app.get_chat_log().add_tool_start(
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

        # Drain all available items from the queue. Keep the latest "start"
        # entry for the live TUI header (most informative — [tool_name] args),
        # while accumulating every start/end pair into run_record.tool_calls
        # so the F2 subagent popup can show the full trace after the fact.
        latest_action = None
        try:
            while True:
                item = _thread_queue.get_nowait()
                action_type, tool_name, arg_str, tool_output, tool_input_ev = item
                if action_type == "start":
                    latest_action = f"[{tool_name}] {arg_str}" if arg_str else f"[{tool_name}]"
                    run_record.tool_calls.append(
                        SubagentToolCall(
                            tool_name=tool_name,
                            args=arg_str,
                            status="running",
                            tool_input=tool_input_ev or {},
                        )
                    )
                elif action_type == "end":
                    for tc in reversed(run_record.tool_calls):
                        if tc.tool_name == tool_name and tc.status == "running":
                            tc.output = tool_output
                            tc.status = "success"
                            break
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
                        textual_app.get_chat_log().update_tool_progress(
                            tool_entry, current_action
                        )
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
        run_record.status = "error"
        run_record.error = error_msg
        if textual_app:
            with contextlib.suppress(Exception):
                textual_app.refresh_subagent_hint()
        if tool_entry and textual_app:
            try:
                textual_app.get_chat_log().finalize_subagent(
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

    # Use cumulative tokens (subagent may have multiple model calls)
    sub_input_tokens = result.cumulative_input_tokens or result.input_tokens
    sub_output_tokens = result.cumulative_output_tokens or result.output_tokens
    sub_cache_read = result.cumulative_cache_read_tokens or result.cache_read_tokens
    sub_cache_creation = result.cumulative_cache_creation_tokens or result.cache_creation_tokens

    run_record.status = "success"
    run_record.response = result.response
    run_record.input_tokens = sub_input_tokens
    run_record.output_tokens = sub_output_tokens
    with contextlib.suppress(Exception):
        from clanker.config import get_default_model

        cm = get_default_model()
        run_record.cost_usd = (
            cm.compute_cost(sub_input_tokens, sub_output_tokens, sub_cache_read, sub_cache_creation)
            if cm else None
        )
    if textual_app:
        with contextlib.suppress(Exception):
            textual_app.refresh_subagent_hint()

    # Add subagent tokens/cost to the parent session tracker (status bar)
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

    # Finalize TUI: just show agent badge with success/failure (no output)
    if tool_entry and textual_app:
        try:
            textual_app.get_chat_log().finalize_subagent(
                tool_entry,
                agent_name,
                result.response,
                success=True,
            )
        except Exception:
            pass

    # Enforce response length limit: if the subagent produced more than
    # _SUBAGENT_MAX_WORDS, write the full output to a temp file and return
    # a truncated summary + file path reference so the parent agent doesn't
    # get flooded with context.
    response_text = result.response
    response_words = len(response_text.split())
    if response_words > _SUBAGENT_MAX_WORDS:
        import tempfile
        from datetime import datetime

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=f"_{agent_name}_{ts}.md",
            delete=False,
            prefix="clanker_",
        )
        tmp.write(response_text)
        tmp.close()

        # Truncate to ~_SUBAGENT_MAX_WORDS at a word boundary
        truncated_words = response_text.split()[:_SUBAGENT_MAX_WORDS]
        response_text = (
            " ".join(truncated_words)
            + f"\n\n---\n"
            f"[Output truncated: {response_words} words total. "
            f"Full output saved to `{tmp.name}`. Read it with `read_file` if needed.]"
        )
        logger.info(
            "Subagent '%s' output truncated from %d words to %d; "
            "full output at %s",
            agent_name,
            response_words,
            _SUBAGENT_MAX_WORDS,
            tmp.name,
        )

    return {
        "success": True,
        "agent": agent_name,
        "response": response_text,
        "input_tokens": sub_input_tokens,
        "output_tokens": sub_output_tokens,
    }
