"""Streaming output handler for real-time responses."""

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass

from clanker.config import Settings
from clanker.tools.bash_tools import CommandRejectedError
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

        # Token tracking
        total_input_tokens = 0
        total_output_tokens = 0
        cache_read_tokens = 0
        cache_creation_tokens = 0
        model_name = ""

        def start_loading():
            """Start the loading spinner."""
            nonlocal loading_live
            if loading_live is None:
                message = console.get_loading_message()
                spinner = Spinner("dots", text=Text(f" {message}", style="cyan"))
                loading_live = Live(spinner, console=rich_console, refresh_per_second=10, transient=True)
                loading_live.start()

        def stop_loading():
            """Stop the loading spinner."""
            nonlocal loading_live
            if loading_live is not None:
                loading_live.stop()
                loading_live = None

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
            # Start loading spinner
            start_loading()

            with _suppress_subprocess_stderr():
                async for event in graph.astream_events(
                    state, config=config, version="v2"
                ):
                    event_type = event.get("event", "")

                    # Collect tool calls
                    if event_type == "on_tool_start":
                        stop_loading()  # Stop loading when tools start
                        if settings.output.show_tool_calls:
                            run_id = event.get("run_id", "")
                            if run_id and run_id not in shown_tool_calls:
                                shown_tool_calls.add(run_id)
                                tool_name = event.get("name", "unknown")
                                tool_input = event.get("data", {}).get("input", {})
                                # Skip bash display when approval is needed (approval prompt shows it)
                                if tool_name == "bash" and not is_yolo_mode():
                                    continue
                                pending_tools.append((tool_name, tool_input))

                    # Flush tools when execution completes
                    elif event_type == "on_tool_end":
                        if pending_tools:
                            flush_pending_tools()
                        # Show tool output (truncated, muted)
                        if settings.output.show_tool_calls:
                            data = event.get("data", {})
                            # Tool output can be in 'output' directly or nested
                            tool_output = data.get("output")
                            # Handle ToolMessage objects
                            if tool_output is None:
                                tool_output = ""
                            elif hasattr(tool_output, "content"):
                                tool_output = tool_output.content
                            elif not isinstance(tool_output, str):
                                tool_output = str(tool_output)
                            if tool_output and tool_output.strip():
                                console.print_tool_result(tool_output)
                        # Restart loading while waiting for next model response
                        start_loading()

                    # New model run - reset for final response only
                    elif event_type == "on_chat_model_start":
                        run_id = event.get("run_id", "")
                        if run_id != current_model_run:
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

                            # Track first content but don't stop loading yet
                            # (we'll stop when we get actual response, not thinking)
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
                                # Handle <think>...</think> tags (DeepSeek, etc.)
                                # Some models output thinking without <think> tag, just </think> at end
                                remaining = content
                                while remaining:
                                    if think_tag_closed:
                                        # Already past thinking - everything is response
                                        stop_loading()  # Stop spinner when response starts
                                        current_response += remaining
                                        remaining = ""
                                    elif in_think_tag:
                                        # Inside explicit <think> tag
                                        end_idx = remaining.find("</think>")
                                        if end_idx != -1:
                                            current_thinking += remaining[:end_idx]
                                            remaining = remaining[end_idx + 8:]
                                            in_think_tag = False
                                            think_tag_closed = True
                                            stop_loading()  # Stop spinner when thinking ends
                                        else:
                                            current_thinking += remaining
                                            remaining = ""
                                    else:
                                        # Check for </think> (implicit thinking mode)
                                        end_idx = remaining.find("</think>")
                                        start_idx = remaining.find("<think>")

                                        if start_idx != -1 and (end_idx == -1 or start_idx < end_idx):
                                            # Found <think> tag first
                                            current_response += remaining[:start_idx]
                                            remaining = remaining[start_idx + 7:]
                                            in_think_tag = True
                                            if not thinking_shown:
                                                console.print_thinking_start()
                                                thinking_shown = True
                                        elif end_idx != -1:
                                            # Found </think> without <think> - all prior is thinking
                                            current_thinking += remaining[:end_idx]
                                            remaining = remaining[end_idx + 8:]
                                            think_tag_closed = True
                                            stop_loading()  # Stop spinner when thinking ends
                                            if not thinking_shown and current_thinking:
                                                console.print_thinking_start()
                                                thinking_shown = True
                                        else:
                                            # No tags yet - buffer as potential thinking
                                            # We'll reclassify if we see </think> later
                                            current_thinking += remaining
                                            if not thinking_shown:
                                                console.print_thinking_start()
                                                thinking_shown = True
                                            remaining = ""

                    # Capture token usage when model completes
                    elif event_type == "on_chat_model_end":
                        output = event.get("data", {}).get("output")
                        if output:
                            # Get model name from response
                            if hasattr(output, "response_metadata"):
                                meta = output.response_metadata
                                model_name = meta.get("model", "") or meta.get("model_name", "")

                            # Get usage from usage_metadata (preferred - works for most providers)
                            if hasattr(output, "usage_metadata") and output.usage_metadata:
                                usage = output.usage_metadata
                                total_input_tokens += usage.get("input_tokens", 0)
                                total_output_tokens += usage.get("output_tokens", 0)
                                # Anthropic cache tokens
                                cache_read_tokens += usage.get("cache_read_input_tokens", 0)
                                cache_creation_tokens += usage.get("cache_creation_input_tokens", 0)

                            # Fallback to response_metadata for Azure OpenAI and others
                            elif hasattr(output, "response_metadata"):
                                meta = output.response_metadata

                                # Try "usage" key first (standard format)
                                usage = meta.get("usage", {})
                                if usage:
                                    total_input_tokens += usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
                                    total_output_tokens += usage.get("output_tokens", 0) or usage.get("completion_tokens", 0)

                                # Azure OpenAI may have token_usage at top level
                                if not usage and "token_usage" in meta:
                                    usage = meta.get("token_usage", {})
                                    total_input_tokens += usage.get("prompt_tokens", 0)
                                    total_output_tokens += usage.get("completion_tokens", 0)

                                # Some Azure responses have it directly in metadata
                                if not usage:
                                    total_input_tokens += meta.get("prompt_tokens", 0)
                                    total_output_tokens += meta.get("completion_tokens", 0)

        except CommandRejectedError as e:
            stop_loading()
            rich_console.print(f"\n[bold yellow]Operation cancelled:[/bold yellow] {e}")
            return StreamResult(
                response="",
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_creation_tokens=cache_creation_tokens,
                model_name=model_name,
            )

        finally:
            stop_loading()  # Ensure loading spinner is stopped

        # If we buffered thinking but never saw </think>, treat it as response
        # This handles models that don't use think tags
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
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            model_name=model_name,
        )

    # Run the async function
    return asyncio.run(_stream_async())
