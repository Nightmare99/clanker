"""Streaming output handler for real-time responses."""

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass

from clanker.config import Settings
from clanker.tools.bash_tools import CommandRejectedError
from clanker.tools.notify_tools import set_notify_callback
from clanker.providers import set_tool_call_callback
from clanker.runtime import is_yolo_mode


@dataclass
class StreamResult:
    """Result from streaming an agent response."""

    response: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    model_name: str = ""
    summarization_occurred: bool = False

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


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


def stream_agent_response_sync(
    settings: Settings,
    checkpointer,
    state: dict,
    config: dict,
    console,
) -> StreamResult:
    """Synchronous wrapper for async stream_agent_response.

    Creates the agent graph inside the async context to ensure MCP tools
    are created in the same event loop where they'll be invoked.

    Args:
        settings: Application settings.
        checkpointer: Checkpointer for persistence.
        state: Initial state for the agent.
        config: Configuration dict with thread_id.
        console: Console instance for output.

    Returns:
        StreamResult with response text and token usage.
    """
    import asyncio

    async def _stream_async() -> StreamResult:
        from rich.live import Live
        from rich.spinner import Spinner
        from rich.text import Text

        from clanker.agent import create_agent_graph_async

        # Create graph inside async context so MCP client is in same event loop
        graph, mcp_client = await create_agent_graph_async(settings, checkpointer)
        current_response = ""  # Buffer for current model run
        current_thinking = ""  # Buffer for thinking content
        shown_tool_calls: set[str] = set()
        pending_tools: list[tuple[str, dict]] = []  # Collect parallel tool calls
        current_model_run: str | None = None  # Track current model run_id
        thinking_shown = False
        in_think_tag = False  # Track if we're inside <think>...</think> tags
        think_tag_closed = False  # Track if </think> has been seen
        rich_console = console._console

        # Loading state
        loading_live: Live | None = None
        first_content_received = False

        # Summarization detection
        # Track model calls before any tools run - if we see 2+ model starts
        # before the first tool, the first was likely summarization
        model_call_count = 0
        tools_started = False
        summarization_detected = False
        summarization_spinner_shown = False

        # Token tracking
        # input_tokens: overwritten each call (last call re-sends full history)
        # output_tokens: overwritten each call (last input already encodes prior outputs)
        # cumulative_output_tokens: summed across all calls (for cost accounting)
        last_input_tokens = 0
        last_output_tokens = 0
        cumulative_output_tokens = 0
        last_cache_read_tokens = 0
        last_cache_creation_tokens = 0
        model_name = ""

        def start_loading(message: str | None = None):
            """Start the loading spinner."""
            nonlocal loading_live
            if loading_live is None:
                msg = message or console.get_loading_message()
                spinner = Spinner("dots", text=Text(f" {msg}", style="cyan"))
                loading_live = Live(spinner, console=rich_console, refresh_per_second=10, transient=True)
                loading_live.start()

        def stop_loading():
            """Stop the loading spinner."""
            nonlocal loading_live
            if loading_live is not None:
                loading_live.stop()
                loading_live = None

        def update_loading(message: str):
            """Update the loading spinner message."""
            nonlocal loading_live
            if loading_live is not None:
                spinner = Spinner("dots", text=Text(f" {message}", style="cyan"))
                loading_live.update(spinner)

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

        # Register the notify callback
        def _notify_callback(message: str, level: str) -> None:
            console.print_notify(message, level)

        set_notify_callback(_notify_callback)

        # Register Copilot SDK tool call callback
        def _copilot_tool_callback(tool_name: str, args: dict, result: str | None) -> None:
            """Called by Copilot SDK when tools are executed."""
            if result is None:
                # Tool starting - show the tool call
                if settings.output.show_tool_calls:
                    stop_loading()
                    console.print_tool_use(tool_name, args)
            else:
                # Tool completed - show the result preview
                if settings.output.show_tool_calls and result and result.strip():
                    console.print_tool_result(result, tool_name=tool_name)
                start_loading()

        set_tool_call_callback(_copilot_tool_callback)

        try:
            # Start loading spinner
            start_loading()

            with _suppress_subprocess_stderr():
                async for event in graph.astream_events(
                    state, config=config, version="v2"
                ):
                    event_type = event.get("event", "")

                    # Collect tool calls
                    if event_type == "on_tool_start":
                        tools_started = True
                        stop_loading()
                        if settings.output.show_tool_calls:
                            run_id = event.get("run_id", "")
                            if run_id and run_id not in shown_tool_calls:
                                shown_tool_calls.add(run_id)
                                tool_name = event.get("name", "unknown")
                                tool_input = event.get("data", {}).get("input", {})
                                # Skip bash display when approval is needed
                                if tool_name == "bash" and not is_yolo_mode():
                                    continue
                                # Skip notify - the tool itself handles display
                                if tool_name == "notify":
                                    continue
                                pending_tools.append((tool_name, tool_input))

                    # Flush tools when execution completes
                    elif event_type == "on_tool_end":
                        if pending_tools:
                            flush_pending_tools()
                        tool_name_end = event.get("name", "")
                        if tool_name_end == "notify":
                            start_loading()
                            continue
                        # Show tool output
                        if settings.output.show_tool_calls:
                            data = event.get("data", {})
                            tool_output = data.get("output")
                            if tool_output is None:
                                tool_output = ""
                            elif hasattr(tool_output, "content"):
                                tool_output = tool_output.content
                            if isinstance(tool_output, list):
                                tool_output = "\n".join(str(item) for item in tool_output)
                            elif not isinstance(tool_output, str):
                                tool_output = str(tool_output)
                            if tool_output and tool_output.strip():
                                console.print_tool_result(tool_output, tool_name=tool_name_end)
                        start_loading()

                    # Track model calls to detect summarization
                    elif event_type == "on_chat_model_start":
                        run_id = event.get("run_id", "")
                        if run_id != current_model_run:
                            model_call_count += 1

                            # If this is the 2nd+ model call before tools started,
                            # the previous call was likely summarization
                            if model_call_count == 1 and not tools_started:
                                # First model call - could be summarization, show special message
                                # We'll know for sure if we see another model start
                                pass
                            elif model_call_count == 2 and not tools_started and not summarization_spinner_shown:
                                # Second model call before tools = first was summarization!
                                summarization_detected = True
                                summarization_spinner_shown = True
                                stop_loading()
                                console.print_info("*WHIRR* Compressing memory banks...")
                                start_loading()

                            if pending_tools:
                                flush_pending_tools()
                            current_response = ""
                            current_thinking = ""
                            thinking_shown = False
                            first_content_received = False
                            in_think_tag = False
                            think_tag_closed = False
                            current_model_run = run_id

                    # Stream text from LLM
                    elif event_type == "on_chat_model_stream":
                        chunk = event.get("data", {}).get("chunk")
                        if chunk:
                            content = getattr(chunk, "content", None)

                            if content and not first_content_received:
                                first_content_received = True

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
                                                stop_loading()
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
                                                stop_loading()
                                                current_response += text

                            # Handle string content (standard format)
                            elif content and isinstance(content, str):
                                remaining = content
                                while remaining:
                                    if think_tag_closed:
                                        stop_loading()
                                        current_response += remaining
                                        remaining = ""
                                    elif in_think_tag:
                                        end_idx = remaining.find("</think>")
                                        if end_idx != -1:
                                            current_thinking += remaining[:end_idx]
                                            remaining = remaining[end_idx + 8:]
                                            in_think_tag = False
                                            think_tag_closed = True
                                            stop_loading()
                                        else:
                                            current_thinking += remaining
                                            remaining = ""
                                    else:
                                        end_idx = remaining.find("</think>")
                                        start_idx = remaining.find("<think>")

                                        if start_idx != -1 and (end_idx == -1 or start_idx < end_idx):
                                            current_response += remaining[:start_idx]
                                            remaining = remaining[start_idx + 7:]
                                            in_think_tag = True
                                            if not thinking_shown:
                                                console.print_thinking_start()
                                                thinking_shown = True
                                        elif end_idx != -1:
                                            current_thinking += remaining[:end_idx]
                                            remaining = remaining[end_idx + 8:]
                                            think_tag_closed = True
                                            stop_loading()
                                            if not thinking_shown and current_thinking:
                                                console.print_thinking_start()
                                                thinking_shown = True
                                        else:
                                            current_thinking += remaining
                                            if not thinking_shown:
                                                console.print_thinking_start()
                                                thinking_shown = True
                                            remaining = ""

                    # Capture token usage when model completes
                    elif event_type == "on_chat_model_end":
                        output = event.get("data", {}).get("output")
                        if output:
                            if hasattr(output, "response_metadata"):
                                meta = output.response_metadata
                                model_name = meta.get("model", "") or meta.get("model_name", "")

                            if hasattr(output, "usage_metadata") and output.usage_metadata:
                                usage = output.usage_metadata
                                last_input_tokens = usage.get("input_tokens", 0)
                                last_output_tokens = usage.get("output_tokens", 0)
                                cumulative_output_tokens += last_output_tokens
                                last_cache_read_tokens = usage.get("cache_read_input_tokens", 0)
                                last_cache_creation_tokens = usage.get("cache_creation_input_tokens", 0)

                            elif hasattr(output, "response_metadata"):
                                meta = output.response_metadata
                                usage = meta.get("usage", {})
                                if usage:
                                    last_input_tokens = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
                                    last_output_tokens = usage.get("output_tokens", 0) or usage.get("completion_tokens", 0)
                                    cumulative_output_tokens += last_output_tokens

                                if not usage and "token_usage" in meta:
                                    usage = meta.get("token_usage", {})
                                    last_input_tokens = usage.get("prompt_tokens", 0)
                                    last_output_tokens = usage.get("completion_tokens", 0)
                                    cumulative_output_tokens += last_output_tokens

                                if not usage:
                                    last_input_tokens = meta.get("prompt_tokens", 0)
                                    last_output_tokens = meta.get("completion_tokens", 0)
                                    cumulative_output_tokens += last_output_tokens

        except CommandRejectedError as e:
            stop_loading()
            rich_console.print(f"\n[bold yellow]Operation cancelled:[/bold yellow] {e}")
            return StreamResult(
                response="",
                input_tokens=last_input_tokens,
                output_tokens=last_output_tokens,
                cache_read_tokens=last_cache_read_tokens,
                cache_creation_tokens=last_cache_creation_tokens,
                model_name=model_name,
                summarization_occurred=summarization_detected,
            )

        except (KeyboardInterrupt, asyncio.CancelledError):
            stop_loading()
            rich_console.print("\n[bold yellow]*BZZZT*[/bold yellow] Agent halted. Control returned to you. [bold yellow]*CLANK*[/bold yellow]")
            return StreamResult(
                response=current_response,
                input_tokens=last_input_tokens,
                output_tokens=last_output_tokens,
                cache_read_tokens=last_cache_read_tokens,
                cache_creation_tokens=last_cache_creation_tokens,
                model_name=model_name,
                summarization_occurred=summarization_detected,
            )

        finally:
            stop_loading()
            set_notify_callback(None)
            set_tool_call_callback(None)

        # If we buffered thinking but never saw </think>, treat it as response
        if current_thinking and not think_tag_closed and not current_response:
            current_response = current_thinking
            current_thinking = ""

        # Print final response as plain text
        if current_response.strip():
            rich_console.print(current_response)

        # Show thinking summary if present
        if current_thinking:
            console.print_thinking(current_thinking)

        return StreamResult(
            response=current_response,
            input_tokens=last_input_tokens,
            output_tokens=last_output_tokens,
            cache_read_tokens=last_cache_read_tokens,
            cache_creation_tokens=last_cache_creation_tokens,
            model_name=model_name,
            summarization_occurred=summarization_detected,
        )

    # Run the async function — KeyboardInterrupt (Ctrl+C) may surface here
    # if it fires between asyncio yield points; catch it and return a clean result.
    try:
        return asyncio.run(_stream_async())
    except KeyboardInterrupt:
        return StreamResult(response="")
