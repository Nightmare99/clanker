"""Streaming output handler for real-time responses."""

import asyncio
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass

from clanker.config import Settings
from clanker.tools.bash_tools import CommandRejectedError
from clanker.tools.notify_tools import set_notify_callback
from clanker.providers import set_tool_call_callback, get_tool_call_callback
from clanker.runtime import is_yolo_mode
from clanker.ui.tool_display import ToolDisplayHandler, normalize_tool_output

# Persistent event loop for maintaining Copilot session across messages
_persistent_loop: asyncio.AbstractEventLoop | None = None


def _get_or_create_loop() -> asyncio.AbstractEventLoop:
    """Get or create a persistent event loop for the session."""
    global _persistent_loop
    if _persistent_loop is None or _persistent_loop.is_closed():
        _persistent_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_persistent_loop)
    return _persistent_loop


def cleanup_event_loop() -> None:
    """Clean up the persistent event loop. Call on exit."""
    global _persistent_loop
    if _persistent_loop is not None and not _persistent_loop.is_closed():
        _persistent_loop.close()
        _persistent_loop = None


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
    # Copilot-specific: premium requests quota info
    quota_remaining: float | None = None  # Percentage remaining (0-100)
    quota_used: int | None = None  # Requests used
    quota_limit: int | None = None  # Total requests limit

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

        # Unified tool display handler for all providers
        tool_handler = ToolDisplayHandler(
            console=console,
            show_tool_calls=settings.output.show_tool_calls,
            on_tool_start=stop_loading,
            on_tool_end=start_loading,
        )

        # Register the notify callback
        def _notify_callback(message: str, level: str) -> None:
            console.print_notify(message, level)

        set_notify_callback(_notify_callback)

        # Register unified tool callback for Copilot SDK
        set_tool_call_callback(tool_handler.create_callback())

        try:
            # Start loading spinner
            start_loading()

            # Add recursion limit to config (default 100 is too low for complex tasks)
            stream_config = {**config, "recursion_limit": 500}

            with _suppress_subprocess_stderr():
                async for event in graph.astream_events(
                    state, config=stream_config, version="v2"
                ):
                    event_type = event.get("event", "")

                    # Show tool calls immediately (don't batch)
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
                                # Show tool immediately for proper interleaving
                                tool_handler.show_tool(tool_name, tool_input)

                    # Show tool result
                    elif event_type == "on_tool_end":
                        tool_name_end = event.get("name", "")
                        if tool_name_end == "notify":
                            start_loading()
                            continue
                        # Show tool output
                        if settings.output.show_tool_calls:
                            data = event.get("data", {})
                            tool_output = normalize_tool_output(data.get("output"))
                            tool_handler.show_tool_result(tool_name_end, tool_output)
                        # Clear tracking so tool can be called again
                        tool_handler.clear_tool_tracking(tool_name_end)
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

                            if tool_handler.has_pending_tools():
                                tool_handler.flush_pending_tools()
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

    # Run the async function using persistent loop to maintain Copilot session
    # KeyboardInterrupt (Ctrl+C) may surface here if it fires between asyncio yield points
    try:
        loop = _get_or_create_loop()
        return loop.run_until_complete(_stream_async())
    except KeyboardInterrupt:
        return StreamResult(response="")


def stream_copilot_response_sync(
    settings: Settings,
    copilot_manager,
    prompt: str,
    model: str,
    working_directory: str,
    console,
) -> StreamResult:
    """Stream a response using Copilot SDK directly.

    Uses Copilot's native session management instead of LangGraph.

    Args:
        settings: Application settings.
        copilot_manager: CopilotSessionManager instance.
        prompt: User's message.
        model: Copilot model ID.
        working_directory: Current working directory.
        console: Console instance for output.

    Returns:
        StreamResult with response text and token usage.
    """
    async def _stream_copilot_async() -> StreamResult:
        from rich.live import Live
        from rich.spinner import Spinner
        from rich.text import Text

        from clanker.agent.prompts import get_system_prompt
        from clanker.tools import ALL_TOOLS
        from clanker.providers.github_copilot import _convert_langchain_tools_to_copilot

        rich_console = console._console
        current_response = ""

        # Token tracking
        last_input_tokens = 0
        last_output_tokens = 0

        # Loading state
        loading_live: Live | None = None

        def start_loading(message: str | None = None):
            nonlocal loading_live
            if loading_live is None:
                msg = message or console.get_loading_message()
                spinner = Spinner("dots", text=Text(f" {msg}", style="cyan"))
                loading_live = Live(spinner, console=rich_console, refresh_per_second=10, transient=True)
                loading_live.start()

        def stop_loading():
            nonlocal loading_live
            if loading_live is not None:
                loading_live.stop()
                loading_live = None

        # Tool display handler
        tool_handler = ToolDisplayHandler(
            console=console,
            show_tool_calls=settings.output.show_tool_calls,
            on_tool_start=stop_loading,
            on_tool_end=start_loading,
        )

        # Register notify callback
        def _notify_callback(message: str, level: str) -> None:
            console.print_notify(message, level)

        set_notify_callback(_notify_callback)

        # Register tool callback for Copilot SDK
        set_tool_call_callback(tool_handler.create_callback())

        try:
            # Load built-in tools (non-MCP)
            tools = list(ALL_TOOLS)

            # Convert built-in tools to Copilot format
            copilot_tools = _convert_langchain_tools_to_copilot(tools)

            # Build MCP server config for native Copilot SDK support
            mcp_servers = None
            if settings.mcp.enabled and settings.mcp.servers:
                from copilot.types import MCPLocalServerConfig, MCPRemoteServerConfig
                mcp_servers = {}
                for name, server in settings.mcp.servers.items():
                    if not server.enabled:
                        continue
                    if server.transport == "stdio" and server.command:
                        config_kwargs = {
                            "command": server.command,
                            "args": server.args or [],
                            "tools": ["*"],
                        }
                        if server.env:
                            config_kwargs["env"] = server.env
                        mcp_servers[name] = MCPLocalServerConfig(**config_kwargs)
                    elif server.transport == "sse" and server.url:
                        mcp_servers[name] = MCPRemoteServerConfig(
                            type="sse",
                            url=server.url,
                            tools=["*"],
                        )
                if mcp_servers:
                    from clanker.logging import get_logger
                    get_logger("streaming").info("Configured %d MCP servers for Copilot SDK: %s", len(mcp_servers), list(mcp_servers.keys()))

            # Get system prompt
            system_prompt = get_system_prompt()

            # Start loading
            start_loading()

            # Get or create session with native MCP support
            session = await copilot_manager.get_or_create_session(
                model=model,
                tools=copilot_tools,
                system_message=system_prompt,
                mcp_servers=mcp_servers,
            )

            # Event handler for streaming - use mutable containers to share state
            content_parts = []
            usage_data = {}
            done_event = asyncio.Event()
            error_holder = [None]  # Use list to allow mutation in nested function

            def handle_event(event):
                event_type = event.type.value if hasattr(event.type, 'value') else str(event.type)

                # Log MCP and session-related events for debugging
                mcp_events = ["session.mcp_servers_loaded", "session.mcp_server_status_changed",
                             "mcp.oauth_required", "mcp.oauth_completed", "session.tools_updated",
                             "session.error", "session.warning"]
                if event_type in mcp_events or "mcp" in event_type.lower():
                    from clanker.logging import get_logger
                    get_logger("streaming").info("SDK event [%s]: %s", event_type, event.data)

                if event_type == "assistant.message_delta":
                    delta = getattr(event.data, 'delta_content', None) or ""
                    if delta:
                        stop_loading()
                        content_parts.append(delta)
                elif event_type == "assistant.message":
                    content = getattr(event.data, 'content', None)
                    if content:
                        stop_loading()
                        content_parts.clear()
                        content_parts.append(content)
                elif event_type == "assistant.usage":
                    usage_data['input_tokens'] = getattr(event.data, 'input_tokens', 0)
                    usage_data['output_tokens'] = getattr(event.data, 'output_tokens', 0)
                    # Capture quota snapshots if available (premium requests remaining)
                    quota_snapshots = getattr(event.data, 'quota_snapshots', None) or getattr(event.data, 'quotaSnapshots', None)
                    if quota_snapshots:
                        usage_data['quota_snapshots'] = quota_snapshots
                    copilot_usage = getattr(event.data, 'copilot_usage', None) or getattr(event.data, 'copilotUsage', None)
                    if copilot_usage:
                        usage_data['copilot_usage'] = copilot_usage
                elif event_type == "tool.execution_start":
                    tool_name = getattr(event.data, 'tool_name', None) or getattr(event.data, 'toolName', 'unknown')
                    arguments = (
                        getattr(event.data, 'arguments', None) or
                        getattr(event.data, 'toolArgs', None) or
                        getattr(event.data, 'tool_args', None) or
                        {}
                    )
                    if hasattr(arguments, 'model_dump'):
                        arguments = arguments.model_dump()
                    elif hasattr(arguments, '__dict__'):
                        arguments = vars(arguments)

                    callback = get_tool_call_callback()
                    if callback:
                        try:
                            callback(tool_name, arguments, None)
                        except Exception:
                            pass
                elif event_type == "tool.execution_complete":
                    tool_name = getattr(event.data, 'tool_name', None) or getattr(event.data, 'toolName', 'unknown')
                    result = getattr(event.data, 'result', None)
                    result_str = normalize_tool_output(result)

                    callback = get_tool_call_callback()
                    if callback and result_str:
                        try:
                            callback(tool_name, {}, result_str)
                        except Exception:
                            pass
                elif event_type == "session.idle":
                    done_event.set()
                elif event_type == "session.error":
                    error_holder[0] = getattr(event.data, 'message', 'Unknown error')
                    done_event.set()

            # Clear any existing handlers and register fresh one
            # This prevents handler accumulation when session is reused
            if hasattr(session, '_event_handlers'):
                session._event_handlers.clear()
            session.on(handle_event)

            # Send message and wait
            with _suppress_subprocess_stderr():
                response = await session.send_and_wait(prompt)

            # Extract content if events didn't capture it
            if not content_parts and response:
                if hasattr(response, 'data') and hasattr(response.data, 'content'):
                    content_parts = [response.data.content]
                elif hasattr(response, 'content'):
                    content_parts = [response.content]

            if error_holder[0]:
                raise RuntimeError(f"Session error: {error_holder[0]}")

            current_response = "".join(content_parts)
            last_input_tokens = usage_data.get("input_tokens", 0)
            last_output_tokens = usage_data.get("output_tokens", 0)

            # Extract quota info if available (premium_interactions)
            quota_remaining = None
            quota_used = None
            quota_limit = None
            quota_snapshots = usage_data.get("quota_snapshots")
            if quota_snapshots:
                # Look for premium_interactions quota
                snapshot = quota_snapshots.get("premium_interactions")
                if snapshot:
                    # QuotaSnapshot object has these attributes
                    remaining_pct = getattr(snapshot, 'remaining_percentage', None)
                    used = getattr(snapshot, 'used_requests', None)
                    limit = getattr(snapshot, 'entitlement_requests', None)
                    is_unlimited = getattr(snapshot, 'is_unlimited_entitlement', False)

                    if not is_unlimited and remaining_pct is not None:
                        quota_remaining = float(remaining_pct)
                        if used is not None:
                            quota_used = int(used)
                        if limit is not None and limit > 0:
                            quota_limit = int(limit)

        except CommandRejectedError as e:
            stop_loading()
            rich_console.print(f"\n[bold yellow]Operation cancelled:[/bold yellow] {e}")
            return StreamResult(
                response="",
                input_tokens=last_input_tokens,
                output_tokens=last_output_tokens,
                model_name=model,
            )

        except (KeyboardInterrupt, asyncio.CancelledError):
            stop_loading()
            rich_console.print("\n[bold yellow]*BZZZT*[/bold yellow] Agent halted. Control returned to you. [bold yellow]*CLANK*[/bold yellow]")
            return StreamResult(
                response=current_response,
                input_tokens=last_input_tokens,
                output_tokens=last_output_tokens,
                model_name=model,
            )

        finally:
            stop_loading()
            set_notify_callback(None)
            set_tool_call_callback(None)

        # Print final response
        if current_response.strip():
            rich_console.print(current_response)

        return StreamResult(
            response=current_response,
            input_tokens=last_input_tokens,
            output_tokens=last_output_tokens,
            model_name=model,
            quota_remaining=quota_remaining,
            quota_used=quota_used,
            quota_limit=quota_limit,
        )

    # Run using persistent loop
    try:
        loop = _get_or_create_loop()
        return loop.run_until_complete(_stream_copilot_async())
    except KeyboardInterrupt:
        return StreamResult(response="")
