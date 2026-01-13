"""Streaming output handler for real-time responses."""

import json
import os
import sys
from contextlib import contextmanager
from typing import Any

from rich.console import Console as RichConsole
from rich.live import Live
from rich.text import Text

from clanker.config import get_settings
from clanker.ui.markup_adapter import extract_code_blocks, markdown_to_rich


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


class StreamHandler:
    """Handle streaming output from the agent."""

    def __init__(self, console: RichConsole | None = None):
        """Initialize the stream handler.

        Args:
            console: Optional Rich console instance.
        """
        self._console = console or RichConsole()
        self._settings = get_settings()
        self._buffer = ""
        self._live: Live | None = None

    def start(self) -> None:
        """Start streaming mode."""
        self._buffer = ""
        if self._settings.output.stream_responses:
            self._live = Live(
                Text(""),
                console=self._console,
                refresh_per_second=10,
                transient=True,
            )
            self._live.start()

    def update(self, chunk: str) -> None:
        """Update with a new chunk of text.

        Args:
            chunk: New text chunk to add.
        """
        self._buffer += chunk

        if self._live:
            # Update live display with Rich markup text (no code blocks)
            cleaned, _ = extract_code_blocks(self._buffer)
            self._live.update(Text.from_markup(markdown_to_rich(cleaned)))
        elif self._settings.output.stream_responses:
            # Fallback: direct print without Live
            sys.stdout.write(chunk)
            sys.stdout.flush()

    def finish(self) -> str:
        """Finish streaming and return the complete text.

        Returns:
            The complete streamed text.
        """
        if self._live:
            self._live.stop()
            self._live = None

            # Print final output: text + extracted code blocks
            cleaned, code_blocks = extract_code_blocks(self._buffer)
            if cleaned.strip():
                self._console.print(Text.from_markup(markdown_to_rich(cleaned)))
            for lang, code in code_blocks:
                self._console.print()
                # Delegate syntax highlighting to Console
                try:
                    # Console wrapper provides print_code
                    from clanker.ui.console import Console

                    if isinstance(self._console, Console):
                        self._console.print_code(code, language=lang)
                    else:
                        self._console.print(code)
                except Exception:
                    self._console.print(code)

        return self._buffer

    def abort(self) -> None:
        """Abort streaming."""
        if self._live:
            self._live.stop()
            self._live = None
        self._buffer = ""


async def stream_agent_response(graph, state: dict, config: dict, console) -> str:
    """Stream agent responses in real-time.

    Args:
        graph: The compiled LangGraph agent.
        state: Initial state for the agent.
        config: Configuration dict with thread_id.
        console: Console instance for output.

    Returns:
        The complete response text.
    """
    settings = get_settings()
    handler = StreamHandler(console._console)

    full_response = ""
    handler.start()

    try:
        async for event in graph.astream_events(state, config=config, version="v2"):
            kind = event.get("event", "")

            if kind == "on_chat_model_stream":
                # Stream token from LLM
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    handler.update(chunk.content)
                    full_response += chunk.content

            elif kind == "on_tool_start" and settings.output.show_tool_calls:
                # Tool invocation starting
                tool_name = event.get("name", "unknown")
                handler.finish()  # Flush current buffer
                console.print_tool_call(tool_name)
                handler.start()  # Restart for next output

            elif kind == "on_tool_end" and settings.output.show_tool_calls:
                # Tool completed
                output = event.get("data", {}).get("output", "")
                if output:
                    console.print_tool_result(str(output))

    except Exception as e:
        handler.abort()
        raise

    handler.finish()
    return full_response


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
        final_response = ""  # Only the last model run's output
        current_thinking = ""  # Buffer for thinking content
        shown_tool_calls: set[str] = set()
        pending_tools: list[tuple[str, dict]] = []  # Collect parallel tool calls
        current_model_run: str | None = None  # Track current model run_id
        thinking_shown = False  # Track if we've shown thinking indicator
        rich_console = console._console

        # Use Live display for streaming with markdown rendering
        # transient=False keeps the final output visible (no need to reprint)
        live = Live(
            Text(""),
            console=rich_console,
            refresh_per_second=12,
            transient=False,
        )

        live.start()

        def flush_pending_tools():
            """Display any pending tool calls."""
            nonlocal pending_tools
            if not pending_tools:
                return
            live.stop()
            if len(pending_tools) > 1:
                console.print_parallel_tools(pending_tools)
            else:
                tool_name, tool_input = pending_tools[0]
                console.print_tool_use(tool_name, tool_input)
                # Show diff/content for file write operations
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
            pending_tools = []
            live.start()

        try:
            # Suppress stderr from MCP subprocesses during streaming
            with _suppress_subprocess_stderr():
                # Use astream_events for complete tool call information
                async for event in graph.astream_events(
                    state, config=config, version="v2"
                ):
                    event_type = event.get("event", "")

                    # Handle tool start - collect for parallel display
                    if event_type == "on_tool_start" and settings.output.show_tool_calls:
                        run_id = event.get("run_id", "")
                        if run_id and run_id not in shown_tool_calls:
                            shown_tool_calls.add(run_id)
                            tool_name = event.get("name", "unknown")
                            tool_input = event.get("data", {}).get("input", {})
                            pending_tools.append((tool_name, tool_input))

                    # Handle tool end - flush all pending tools when first one completes
                    elif event_type == "on_tool_end":
                        if pending_tools:
                            flush_pending_tools()

                    # Handle new model run starting - reset buffer
                    elif event_type == "on_chat_model_start":
                        run_id = event.get("run_id", "")
                        if run_id != current_model_run:
                            # Flush any pending tools first
                            if pending_tools:
                                flush_pending_tools()
                            # New model run - save previous and reset
                            if current_response:
                                final_response = current_response
                            current_response = ""
                            current_thinking = ""
                            thinking_shown = False
                            current_model_run = run_id
                            live.update(Text(""))

                    # Handle streaming text from the LLM
                    elif event_type == "on_chat_model_stream":
                        chunk = event.get("data", {}).get("chunk")
                        if chunk:
                            # Check for thinking content (Anthropic extended thinking)
                            content = getattr(chunk, "content", None)

                            # Handle list content (Anthropic format with thinking blocks)
                            if isinstance(content, list):
                                for block in content:
                                    if isinstance(block, dict):
                                        block_type = block.get("type", "")
                                        if block_type == "thinking":
                                            thinking_text = block.get("thinking", "")
                                            if thinking_text:
                                                current_thinking += thinking_text
                                                if not thinking_shown:
                                                    live.stop()
                                                    console.print_thinking_start()
                                                    live.start()
                                                    thinking_shown = True
                                        elif block_type == "text":
                                            text = block.get("text", "")
                                            if text:
                                                current_response += text
                                                cleaned, _ = extract_code_blocks(current_response)
                                                live.update(Text.from_markup(markdown_to_rich(cleaned)))
                                    elif hasattr(block, "type"):
                                        # Object-style content block
                                        if block.type == "thinking":
                                            thinking_text = getattr(block, "thinking", "")
                                            if thinking_text:
                                                current_thinking += thinking_text
                                                if not thinking_shown:
                                                    live.stop()
                                                    console.print_thinking_start()
                                                    live.start()
                                                    thinking_shown = True
                                        elif block.type == "text":
                                            text = getattr(block, "text", "")
                                            if text:
                                                current_response += text
                                                cleaned, _ = extract_code_blocks(current_response)
                                                live.update(Text.from_markup(markdown_to_rich(cleaned)))

                            # Handle string content (standard format)
                            elif content and isinstance(content, str):
                                current_response += content
                                # Update live display with rich text (markup)
                                cleaned, _ = extract_code_blocks(current_response)
                                live.update(Text.from_markup(markdown_to_rich(cleaned)))

        finally:
            live.stop()

        # Use the last model run's response (current_response has the final output)
        output = current_response if current_response else final_response

        # Show thinking summary if we had thinking content
        if current_thinking:
            console.print_thinking(current_thinking)

        # Extract and print code blocks with syntax highlighting
        # (text content is already displayed by the Live display)
        _, code_blocks = extract_code_blocks(output)
        for lang, code in code_blocks:
            rich_console.print()
            console.print_code(code, language=lang)

        return output

    # Run the async function
    return asyncio.run(_stream_async())
