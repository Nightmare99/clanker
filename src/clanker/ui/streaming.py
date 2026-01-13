"""Streaming output handler for real-time responses."""

import os
import sys
from contextlib import contextmanager

from clanker.config import get_settings


@contextmanager
def _suppress_subprocess_stderr():
    """Suppress stderr from subprocesses (like MCP servers) at fd level."""
    try:
        original_stderr_fd = sys.stderr.fileno()
        saved_stderr_fd = os.dup(original_stderr_fd)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, original_stderr_fd)
        os.close(devnull)
        yield
    except (OSError, ValueError):
        # If we can't redirect (e.g., no real stderr), just continue
        yield
    else:
        os.dup2(saved_stderr_fd, original_stderr_fd)
        os.close(saved_stderr_fd)


def stream_agent_response_sync(graph, state: dict, config: dict, console) -> str:
    """Synchronous wrapper for async stream_agent_response.

    Uses asyncio to execute the async streaming function.
    This ensures MCP tools (which are async-only) work correctly.

    Args:
        graph: The compiled LangGraph agent.
        state: Initial state for the agent.
        config: Configuration dict with thread_id.
        console: Console instance for output.

    Returns:
        The complete response text.
    """
    import asyncio
    import nest_asyncio

    # Allow nested event loops (needed when called from sync context with existing loop)
    nest_asyncio.apply()

    async def _stream_async() -> str:
        settings = get_settings()
        current_response = ""  # Buffer for current model run
        current_thinking = ""  # Buffer for thinking content
        shown_tool_calls: set[str] = set()
        pending_tools: list[tuple[str, dict]] = []  # Collect parallel tool calls
        current_model_run: str | None = None  # Track current model run_id
        thinking_shown = False
        rich_console = console._console

        def show_tool(tool_name: str, tool_input: dict):
            """Display a single tool call with details."""
            console.print_tool_use(tool_name, tool_input)
            if tool_name == "edit_file":
                old_str = tool_input.get("old_string", "")
                new_str = tool_input.get("new_string", "")
                if old_str or new_str:
                    console.print_edit_diff(old_str, new_str)
            elif tool_name == "write_file":
                content = tool_input.get("content", "")
                if content:
                    console.print_write_content(content, is_append=False)
            elif tool_name == "append_file":
                content = tool_input.get("content", "")
                if content:
                    console.print_write_content(content, is_append=True)

        def flush_pending_tools():
            """Display any pending tool calls."""
            nonlocal pending_tools
            if not pending_tools:
                return
            if len(pending_tools) > 1:
                console.print_parallel_tools(pending_tools)
            else:
                show_tool(*pending_tools[0])
            pending_tools = []

        try:
            with _suppress_subprocess_stderr():
                async for event in graph.astream_events(
                    state, config=config, version="v2"
                ):
                    event_type = event.get("event", "")

                    # Collect tool calls
                    if event_type == "on_tool_start" and settings.output.show_tool_calls:
                        run_id = event.get("run_id", "")
                        if run_id and run_id not in shown_tool_calls:
                            shown_tool_calls.add(run_id)
                            tool_name = event.get("name", "unknown")
                            tool_input = event.get("data", {}).get("input", {})
                            pending_tools.append((tool_name, tool_input))

                    # Flush tools when execution completes
                    elif event_type == "on_tool_end":
                        if pending_tools:
                            flush_pending_tools()

                    # New model run - reset for final response only
                    elif event_type == "on_chat_model_start":
                        run_id = event.get("run_id", "")
                        if run_id != current_model_run:
                            if pending_tools:
                                flush_pending_tools()
                            current_response = ""
                            current_thinking = ""
                            thinking_shown = False
                            current_model_run = run_id

                    # Stream text from LLM
                    elif event_type == "on_chat_model_stream":
                        chunk = event.get("data", {}).get("chunk")
                        if chunk:
                            content = getattr(chunk, "content", None)

                            # Handle Anthropic list content (with thinking blocks)
                            if isinstance(content, list):
                                for block in content:
                                    if isinstance(block, dict):
                                        if block.get("type") == "thinking":
                                            thinking_text = block.get("thinking", "")
                                            if thinking_text:
                                                current_thinking += thinking_text
                                                if not thinking_shown:
                                                    console.print_thinking_start()
                                                    thinking_shown = True
                                        elif block.get("type") == "text":
                                            text = block.get("text", "")
                                            if text:
                                                current_response += text
                                    elif hasattr(block, "type"):
                                        if block.type == "thinking":
                                            thinking_text = getattr(block, "thinking", "")
                                            if thinking_text:
                                                current_thinking += thinking_text
                                                if not thinking_shown:
                                                    console.print_thinking_start()
                                                    thinking_shown = True
                                        elif block.type == "text":
                                            text = getattr(block, "text", "")
                                            if text:
                                                current_response += text

                            # Handle string content (standard format)
                            elif content and isinstance(content, str):
                                current_response += content

        finally:
            pass

        # Print final response as plain text
        if current_response.strip():
            rich_console.print(current_response)

        # Show thinking summary if present
        if current_thinking:
            console.print_thinking(current_thinking)

        return current_response

    # Run the async function
    return asyncio.run(_stream_async())
