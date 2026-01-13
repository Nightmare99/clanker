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
        full_response = ""
        shown_tool_calls: set[str] = set()
        rich_console = console._console

        # Use Live display for streaming with markdown rendering
        live = Live(
            Text(""),
            console=rich_console,
            refresh_per_second=12,
            transient=True,  # Clear when done so we can print final version
        )

        live.start()

        try:
            # Suppress stderr from MCP subprocesses during streaming
            with _suppress_subprocess_stderr():
                # Use astream_events for complete tool call information
                async for event in graph.astream_events(
                    state, config=config, version="v2"
                ):
                    event_type = event.get("event", "")

                    # Handle tool start - this has complete args
                    if event_type == "on_tool_start" and settings.output.show_tool_calls:
                        run_id = event.get("run_id", "")
                        if run_id and run_id not in shown_tool_calls:
                            shown_tool_calls.add(run_id)
                            tool_name = event.get("name", "unknown")
                            tool_input = event.get("data", {}).get("input", {})

                            live.stop()
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

                            live.start()

                    # Handle streaming text from the LLM
                    elif event_type == "on_chat_model_stream":
                        chunk = event.get("data", {}).get("chunk")
                        if chunk:
                            content = getattr(chunk, "content", None)
                            if content and isinstance(content, str):
                                full_response += content
                                # Update live display with rich text (markup)
                                cleaned, _ = extract_code_blocks(full_response)
                                live.update(Text.from_markup(markdown_to_rich(cleaned)))

        finally:
            live.stop()

        # Print final rendered rich text (markup)
        cleaned, code_blocks = extract_code_blocks(full_response)
        if cleaned.strip():
            rich_console.print(Text.from_markup(markdown_to_rich(cleaned)))
        for lang, code in code_blocks:
            rich_console.print()
            console.print_code(code, language=lang)

        return full_response

    # Run the async function
    return asyncio.run(_stream_async())
