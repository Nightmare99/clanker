"""Streaming output handler for real-time responses."""

import asyncio
import os
import signal
import sys
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass

from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

from clanker.config import Settings
from clanker.logging import get_logger
from clanker.tools.bash_tools import CommandRejectedError, set_approval_callback
from clanker.tools.notify_tools import set_notify_callback
from clanker.tools.ask_tools import set_ask_callback
from clanker.runtime import is_yolo_mode
from clanker.ui.tool_display import ToolDisplayHandler, normalize_tool_output

# Persistent event loop for the streaming session
_persistent_loop: asyncio.AbstractEventLoop | None = None

# Track the currently running streaming task for signal-based cancellation
_current_streaming_task: asyncio.Task | None = None
_interrupted: bool = False
_current_loading_live = None  # Reference to current loading spinner for interrupt updates


def _cancel_streaming_task() -> None:
    """Signal that the current streaming task should stop.

    Called by signal handler when Ctrl+C is pressed. Sets the interrupt flag
    and updates the spinner. Does NOT cancel the task - the task checks the
    flag and calls session.abort() gracefully to preserve the session.
    """
    global _interrupted, _current_loading_live
    _interrupted = True

    # Update spinner to show stopping message immediately
    if _current_loading_live is not None:
        try:
            spinner = Spinner("dots", text=Text(" Stopping...", style="bold red"))
            _current_loading_live.update(spinner)
        except Exception:
            pass
    # NOTE: We intentionally do NOT cancel the task here.
    # Cancelling would interrupt session.abort() and corrupt the session.
    # Instead, the streaming code checks _interrupted and aborts gracefully.


def _asyncio_exception_handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    """Custom exception handler to suppress expected cleanup errors.

    When Ctrl+C is pressed, in-flight asyncio callbacks may try to set exceptions
    on already-done Futures. This is expected and should not pollute the console.
    """
    exception = context.get("exception")
    message = context.get("message", "")

    # Suppress InvalidStateError during cleanup (Future already done/cancelled)
    if isinstance(exception, asyncio.InvalidStateError):
        return

    # Suppress CancelledError (expected on Ctrl+C)
    if isinstance(exception, asyncio.CancelledError):
        return

    # Suppress ProcessExited with code 0 (clean exit)
    if "ProcessExited" in message and "code 0" in message:
        return

    # Suppress "Task exception was never retrieved" for our streaming tasks
    if "Task exception was never retrieved" in message:
        # Check if it's from our streaming code
        future = context.get("future")
        if future and hasattr(future, "get_coro"):
            coro = future.get_coro()
            coro_name = getattr(coro, "__qualname__", "")
            if "_stream_async" in coro_name:
                return

    # For other exceptions, use default handling
    loop.default_exception_handler(context)


def _get_or_create_loop() -> asyncio.AbstractEventLoop:
    """Get or create a persistent event loop for the session."""
    global _persistent_loop
    if _persistent_loop is None or _persistent_loop.is_closed():
        _persistent_loop = asyncio.new_event_loop()
        _persistent_loop.set_exception_handler(_asyncio_exception_handler)
        asyncio.set_event_loop(_persistent_loop)
    return _persistent_loop


def cleanup_event_loop() -> None:
    """Clean up the persistent event loop. Call on exit."""
    global _persistent_loop
    if _persistent_loop is not None and not _persistent_loop.is_closed():
        _persistent_loop.close()
        _persistent_loop = None


def _teardown_live_displays(rich_console, stop_loading, tool_handler) -> None:
    """Tear down every Rich Live owner so none leak past the turn.

    Two independent owners (the loading spinner and the ToolDisplayHandler) share
    one Rich console, and Rich permits only one active Live at a time. If an
    exception propagates mid-stream and leaves either Live active, the console's
    ``_live`` stays set -- which makes the guarded ``start_loading`` no-op for the
    rest of the session (the spinner silently dies). Call this from the streaming
    ``finally`` blocks.

    Each step is isolated so a failure in one can't prevent the others, and a
    final ``clear_live()`` force-resets the console as a last resort.
    """
    try:
        stop_loading()
    except Exception:
        pass
    try:
        tool_handler.finalize_live()
    except Exception:
        pass
    # Last-resort hard reset: even if the steps above partially failed, ensure the
    # console no longer believes a Live is active so the next turn can start one.
    try:
        rich_console.clear_live()
    except Exception:
        pass


async def _heal_orphaned_tool_calls(graph, config) -> None:
    """Repair orphaned tool_use blocks left in the checkpoint.

    When a turn ends after the model emits an ``AIMessage`` with ``tool_calls``
    but before the tool node writes the matching ``ToolMessage`` -- e.g. the user
    interrupted (Ctrl+C) or rejected a command approval, which raises out of the
    tool node -- the persisted state holds tool_use ids with no tool_result.
    Anthropic-family APIs then reject every subsequent turn with a 400. This reads
    the committed state, detects such orphans, and appends stub ToolMessage
    results so history is valid again.

    Self-healing and idempotent: runs each turn, no-ops when already valid.
    Never raises -- a repair failure must not break the turn.
    """
    heal_logger = get_logger("streaming")
    try:
        from clanker.context import find_orphaned_tool_call_ids, make_tool_result_stubs

        snapshot = await graph.aget_state(config)
        messages = snapshot.values.get("messages", []) if snapshot and snapshot.values else []
        if not messages:
            return

        orphan_ids = find_orphaned_tool_call_ids(messages)
        if not orphan_ids:
            return

        heal_logger.warning(
            "Healing %d orphaned tool_use id(s) from an incomplete turn: %s",
            len(orphan_ids), orphan_ids,
        )
        stubs = make_tool_result_stubs(orphan_ids)
        # as_node="tools" attributes the stub ToolMessages to the tool node so the
        # graph resumes at the model node. Without it, aupdate_state raises
        # KeyError('model') on the create_agent graph and the orphan is never fixed.
        await graph.aupdate_state(config, {"messages": stubs}, as_node="tools")
    except Exception as exc:  # noqa: BLE001 - repair must never break the turn
        heal_logger.warning("Failed to heal orphaned tool calls: %s", exc)


async def _compact_oversized_tool_call_args(graph, config, settings) -> None:
    """Shrink oversized tool-call args in the committed checkpoint after a 413.

    Structural twin of :func:`_heal_orphaned_tool_calls`, but for payload size: a
    proxy/gateway can reject a turn with ``413 Request Entity Too Large`` when
    accumulated large tool-call arguments (e.g. ``write_file`` content) bloat the
    request. This rewrites those args in the persisted state so the *next* turn is
    not stuck re-sending the same oversized history.

    Uses the same ``_truncate_tool_call_args`` helper the request-path middleware
    uses, and relies on ``add_messages`` upsert-by-id (``model_copy`` preserves the
    message ``id``) so trimmed AIMessages REPLACE the originals in place -- no
    reordering, no tool_use/tool_result pairing change. Best-effort; never raises.
    """
    heal_logger = get_logger("streaming")
    try:
        from clanker.agent.middleware import _truncate_tool_call_args

        max_tokens = settings.context.max_tool_call_arg_tokens
        if max_tokens <= 0:
            return

        snapshot = await graph.aget_state(config)
        messages = snapshot.values.get("messages", []) if snapshot and snapshot.values else []
        rewritten = [
            new
            for m in messages
            if (new := _truncate_tool_call_args(m, max_tokens)) is not m
        ]
        if not rewritten:
            return

        heal_logger.warning(
            "Compacting %d oversized tool-call message(s) after a too-large error",
            len(rewritten),
        )
        # as_node="tools" attributes the update to the tool node so the graph
        # resumes at the model node (mirrors _heal_orphaned_tool_calls; without it
        # aupdate_state raises KeyError('model') on the create_agent graph).
        await graph.aupdate_state(config, {"messages": rewritten}, as_node="tools")
    except Exception as exc:  # noqa: BLE001 - unwedge must never break the turn
        heal_logger.warning("Failed to compact oversized tool-call args: %s", exc)


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
    saved_stderr_fd: int | None = None
    original_stderr_fd: int | None = None
    redirecting = False
    try:
        original_stderr_fd = sys.stderr.fileno()
        saved_stderr_fd = os.dup(original_stderr_fd)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, original_stderr_fd)
        os.close(devnull)
        redirecting = True
    except (OSError, ValueError):
        # If we can't redirect (e.g., no real stderr), just continue.
        pass

    try:
        yield
    finally:
        if redirecting and saved_stderr_fd is not None and original_stderr_fd is not None:
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

        from langgraph.errors import GraphRecursionError

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
            global _current_loading_live
            nonlocal loading_live
            # Guard against a second Live: the ToolDisplayHandler owns a separate
            # Live on the same console, and Rich allows only one active at a time.
            # Starting another would raise LiveError ("Only one live display...").
            if loading_live is None and getattr(rich_console, "_live", None) is None:
                msg = message or console.get_loading_message()
                spinner = Spinner("dots", text=Text(f" {msg}", style="cyan"))
                loading_live = Live(spinner, console=rich_console, refresh_per_second=10, transient=True)
                loading_live.start()
                _current_loading_live = loading_live

        def stop_loading():
            """Stop the loading spinner."""
            global _current_loading_live
            nonlocal loading_live
            if loading_live is not None:
                loading_live.stop()
                loading_live = None
                _current_loading_live = None

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
        def _notify_callback(message: str, level: str, title: str | None = None) -> None:
            console.print_notify(message, level, title)

        set_notify_callback(_notify_callback)

        # Register the interactive asker (ask_user tool). Pause the spinner and
        # any tool Live while the selection prompt owns the terminal, then resume.
        def _ask_callback(question, options, *, multi_select, allow_other, allow_cancel):
            from clanker.ui.prompts import select_options

            stop_loading()
            try:
                tool_handler.finalize_live()
            except Exception:
                pass
            try:
                return select_options(
                    question,
                    options,
                    multi_select=multi_select,
                    allow_other=allow_other,
                    allow_cancel=allow_cancel,
                )
            finally:
                start_loading()

        set_ask_callback(_ask_callback)

        # Register the interactive bash-approval prompter. Same spinner/Live
        # coordination as the asker so the arrow-key menu owns the terminal.
        def _approval_callback(question, options, *, preface=None):
            from clanker.ui.prompts import select_options

            stop_loading()
            try:
                tool_handler.finalize_live()
            except Exception:
                pass
            try:
                return select_options(
                    question,
                    options,
                    allow_other=False,
                    allow_cancel=False,
                    preface=preface,
                )
            finally:
                start_loading()

        set_approval_callback(_approval_callback)

        try:
            # Start loading spinner
            start_loading()

            # Add recursion limit to config (default 100 is too low for complex tasks).
            # Configurable so large multi-file lint/test loops don't hit it prematurely.
            stream_config = {**config, "recursion_limit": settings.context.max_agent_steps}

            # Heal any orphaned tool_use left in the checkpoint by a prior
            # interrupted turn, otherwise the API rejects this turn with a 400
            # ("tool_use ids without tool_result"). Self-healing: runs every turn,
            # no-ops when the history is already valid.
            await _heal_orphaned_tool_calls(graph, config)

            with _suppress_subprocess_stderr():
                async for event in graph.astream_events(
                    state, config=stream_config, version="v2"
                ):
                    event_type = event.get("event", "")

                    # Check for interrupt flag (set by the SIGINT handler on Ctrl+C).
                    # The handler intentionally does NOT cancel the task, so we must
                    # break out of the event loop ourselves to return control.
                    if _interrupted:
                        stop_loading()
                        tool_handler.finalize_live()
                        rich_console.print(
                            "\n[bold yellow]*BZZZT*[/bold yellow] Agent halted. "
                            "Control returned to you. [bold yellow]*CLANK*[/bold yellow]"
                        )
                        return StreamResult(
                            response=current_response,
                            input_tokens=last_input_tokens,
                            output_tokens=last_output_tokens,
                            cache_read_tokens=last_cache_read_tokens,
                            cache_creation_tokens=last_cache_creation_tokens,
                            model_name=model_name,
                            summarization_occurred=summarization_detected,
                        )

                    # Show tool calls immediately (don't batch)
                    if event_type == "on_tool_start":
                        tools_started = True
                        if settings.output.show_tool_calls:
                            run_id = event.get("run_id", "")
                            if run_id and run_id not in shown_tool_calls:
                                shown_tool_calls.add(run_id)
                                tool_name = event.get("name", "unknown")
                                tool_input = event.get("data", {}).get("input", {})
                                # Skip run display when approval is needed
                                if tool_name == "run" and not is_yolo_mode():
                                    continue
                                # Skip display-only tools (notify, ask_user) -
                                # they render their own output.
                                if tool_name.lower() in ("notify", "ask_user"):
                                    continue
                                # Queue tool with spinner - result will be
                                # printed together with header when tool ends
                                tool_handler.handle_tool_start(tool_name, tool_input)
                        else:
                            stop_loading()

                    # Show tool result
                    elif event_type == "on_tool_end":
                        tool_name_end = event.get("name", "")
                        if tool_name_end.lower() in ("notify", "ask_user"):
                            start_loading()
                            continue
                        # Show tool header + output together
                        if settings.output.show_tool_calls:
                            data = event.get("data", {})
                            tool_output = normalize_tool_output(data.get("output"))
                            tool_handler.handle_tool_end(tool_name_end, tool_output)
                        else:
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
                                # Cache counts live under input_token_details in
                                # LangChain's usage_metadata (the flat
                                # cache_*_input_tokens keys are raw-Anthropic and
                                # never appear here, so reading them yields 0).
                                details = usage.get("input_token_details") or {}
                                last_cache_read_tokens = details.get("cache_read", 0)
                                last_cache_creation_tokens = details.get("cache_creation", 0)

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

        except GraphRecursionError:
            # The agent looped past the per-turn step budget without finishing.
            # End the turn gracefully (preserving any partial text) instead of
            # crashing; the user can nudge it to continue or raise
            # context.max_agent_steps. Any tool_use left dangling by the aborted
            # turn is repaired by _heal_orphaned_tool_calls on the next turn.
            stop_loading()
            tool_handler.finalize_live()
            limit = settings.context.max_agent_steps
            rich_console.print(
                f"\n[bold yellow]*WHIRR*[/bold yellow] Hit the step limit "
                f"({limit} steps) without finishing. Stopping here so you can "
                f"steer. Say 'continue' to resume, or raise "
                f"[cyan]context.max_agent_steps[/cyan] in config for longer runs."
            )
            return StreamResult(
                response=current_response,
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

        except Exception as exc:  # noqa: BLE001
            # A context-length / payload-too-large rejection (e.g. HTTP 413 from a
            # proxy whose body-byte limit the token-based summarization trigger
            # never catches). Re-raise anything else so cli.py's generic handler
            # still logs genuine bugs. KeyboardInterrupt/CancelledError are
            # BaseException and handled above, so this never swallows them.
            from clanker.context import is_context_length_error

            if not is_context_length_error(exc):
                raise

            stop_loading()
            tool_handler.finalize_live()
            get_logger("streaming").warning(
                "Model call rejected as too large (context/payload): %s", exc
            )
            # Unwedge the persisted state so the next turn isn't stuck re-sending
            # the same oversized history.
            await _compact_oversized_tool_call_args(graph, config, settings)
            rich_console.print(
                "\n[bold yellow]*CLANK*[/bold yellow] That request was too large "
                "for the model endpoint. I've trimmed the bulky bits from history "
                "(large file contents are safe on disk) — try again or rephrase."
            )
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
            _teardown_live_displays(rich_console, stop_loading, tool_handler)
            set_notify_callback(None)
            set_ask_callback(None)
            set_approval_callback(None)

        # If we buffered thinking but never saw </think>, treat it as response
        if current_thinking and not think_tag_closed and not current_response:
            current_response = current_thinking
            current_thinking = ""

        # Print final response
        if current_response.strip():
            console.print_assistant_message(current_response)

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

    # Run the async function using persistent loop with proper signal handling
    global _current_streaming_task, _interrupted
    _interrupted = False

    # Install signal handler to cancel task on Ctrl+C
    original_handler = signal.getsignal(signal.SIGINT)

    def _sigint_handler(signum, frame):
        """Handle SIGINT by cancelling the streaming task."""
        _cancel_streaming_task()

    loop = _get_or_create_loop()

    try:
        signal.signal(signal.SIGINT, _sigint_handler)
        _current_streaming_task = loop.create_task(_stream_async())
        return loop.run_until_complete(_current_streaming_task)
    except asyncio.CancelledError:
        # Task was cancelled via signal handler
        return StreamResult(response="")
    except KeyboardInterrupt:
        # Fallback if interrupt happens outside async context
        _cancel_streaming_task()
        return StreamResult(response="")
    finally:
        _current_streaming_task = None
        signal.signal(signal.SIGINT, original_handler)

