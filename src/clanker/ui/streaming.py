"""Streaming output handler for real-time responses."""

import sys
from typing import Any

from langchain_core.messages import AIMessageChunk, HumanMessage, ToolMessage
from rich.console import Console as RichConsole
from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text

from clanker.config import get_settings


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
            # Update live display with current buffer
            self._live.update(Text(self._buffer))
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

            # Print the final markdown-rendered output
            if self._buffer.strip():
                self._console.print(Markdown(self._buffer))

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
    """Synchronous version of stream_agent_response.

    Uses stream_mode="messages" for fine-grained control over output.

    Args:
        graph: The compiled LangGraph agent.
        state: Initial state for the agent.
        config: Configuration dict with thread_id.
        console: Console instance for output.

    Returns:
        The complete response text.
    """
    settings = get_settings()
    full_response = ""
    shown_tool_calls: set[str] = set()

    for msg, metadata in graph.stream(state, config=config, stream_mode="messages"):
        # Skip human messages (user input) and tool messages (tool results)
        if isinstance(msg, (HumanMessage, ToolMessage)):
            continue

        # Handle AI message chunks
        if isinstance(msg, AIMessageChunk):
            # Check for tool calls first
            if msg.tool_calls and settings.output.show_tool_calls:
                for tool_call in msg.tool_calls:
                    tool_id = tool_call.get("id", "")
                    if tool_id and tool_id not in shown_tool_calls:
                        shown_tool_calls.add(tool_id)
                        console.print_tool_use(
                            tool_call.get("name", "unknown"),
                            tool_call.get("args", {}),
                        )

            # Stream AI content (text response)
            if msg.content and isinstance(msg.content, str):
                sys.stdout.write(msg.content)
                sys.stdout.flush()
                full_response += msg.content

    if full_response:
        print()  # Newline after streaming

    return full_response
