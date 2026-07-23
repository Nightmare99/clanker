"""Streaming output handler for real-time responses.

Coordinates the async agent stream with the Textual TUI. The streaming logic
(orchestration, token tracking, interrupt handling) is unchanged -- only the
rendering layer now pushes into Textual widgets instead of Rich Live displays.
"""

import asyncio
import os
import signal
import sys
import threading
from contextlib import contextmanager, suppress
from dataclasses import dataclass

from clanker.config import Settings
from clanker.logging import get_logger
from clanker.runtime import is_yolo_mode
from clanker.tools.ask_tools import get_ask_callback, set_ask_callback
from clanker.tools.bash_tools import (
    CommandRejectedError,
    get_approval_callback,
    set_approval_callback,
)
from clanker.tools.notify_tools import get_notify_callback, set_notify_callback
from clanker.ui.tool_display import ToolDisplayHandler, normalize_tool_output

_local_state = threading.local()


def get_active_console():
    """Get the currently active Console wrapper instance, or a default one."""
    if getattr(_local_state, "active_console", None) is not None:
        return _local_state.active_console
    from clanker.ui.console import Console
    return Console()

# Persistent event loop for the streaming session
_persistent_loop: asyncio.AbstractEventLoop | None = None

# Track the currently running streaming task for signal-based cancellation
_current_streaming_task: asyncio.Task | None = None
_interrupted: bool = False

# Backward-compatible stub: Textual TUI no longer uses Rich Live spinner.
# Kept so subagent.py and tests that reference it don't break.
_current_loading_live = None


def _cancel_streaming_task() -> None:
    """Signal that the current streaming task should stop."""
    global _interrupted
    _interrupted = True


def _asyncio_exception_handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    """Custom exception handler to suppress expected cleanup errors."""
    exception = context.get("exception")
    message = context.get("message", "")

    if isinstance(exception, asyncio.InvalidStateError):
        return
    if isinstance(exception, asyncio.CancelledError):
        return
    if "ProcessExited" in message and "code 0" in message:
        return
    if "Task exception was never retrieved" in message:
        future = context.get("future")
        if future and hasattr(future, "get_coro"):
            coro = future.get_coro()
            coro_name = getattr(coro, "__qualname__", "")
            if "_stream_async" in coro_name:
                return
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
    """Backward-compatible stub. Textual TUI no longer uses Rich Live displays."""
    with suppress(Exception):
        stop_loading()
    with suppress(Exception):
        tool_handler.finalize_live()
    with suppress(Exception):
        rich_console.clear_live()


async def _heal_orphaned_tool_calls(graph, config) -> None:
    """Repair orphaned tool_use blocks left in the checkpoint."""
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
        await graph.aupdate_state(config, {"messages": stubs}, as_node="tools")
    except Exception as exc:  # noqa: BLE001
        heal_logger.warning("Failed to heal orphaned tool calls: %s", exc)


async def _compact_oversized_tool_call_args(graph, config, settings) -> None:
    """Shrink oversized tool-call args in the committed checkpoint after a 413."""
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
        await graph.aupdate_state(config, {"messages": rewritten}, as_node="tools")
    except Exception as exc:  # noqa: BLE001
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
    """Suppress stderr from subprocesses at fd level."""
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
        pass

    try:
        yield
    finally:
        if redirecting and saved_stderr_fd is not None and original_stderr_fd is not None:
            os.dup2(saved_stderr_fd, original_stderr_fd)
            os.close(saved_stderr_fd)


def _get_tool_arg_summary(tool_name: str, tool_input: dict) -> str:
    """Get a short argument summary for a tool call."""
    args = tool_input or {}
    if tool_name in ("read_file", "write_file", "edit_file", "append_file"):
        return str(args.get("file_path", ""))
    elif tool_name == "execute_shell":
        cmd = str(args.get("command", ""))
        return cmd[:60] if cmd else ""
    elif tool_name == "bash_background":
        name_val = args.get("name")
        name = str(name_val).strip() if name_val is not None else ""
        cmd = str(args.get("command", ""))[:50]
        return f"[{name}] {cmd}" if name else cmd
    elif tool_name in ("bash_status", "bash_output", "bash_wait", "bash_kill"):
        return str(args.get("job_id", "all"))
    elif tool_name == "glob_search":
        return str(args.get("pattern", "*"))
    elif tool_name == "grep_search":
        pat = str(args.get("pattern", ""))
        return pat[:40] if pat else ""
    elif tool_name == "list_directory":
        return str(args.get("path", "."))
    elif tool_name == "web_search":
        return str(args.get("query", ""))[:60]
    elif tool_name == "web_read":
        return str(args.get("url", ""))[:80]
    elif tool_name == "load_skill":
        return str(args.get("name", ""))
    else:
        for key in ["query", "path", "url", "input", "text", "command", "name"]:
            if key in args:
                val = str(args[key])
                return val[:40]
        return ""


async def stream_agent_response_async(
    settings: Settings,
    checkpointer,
    state: dict,
    config: dict,
    console,
    tools: list | None = None,
    middleware: list | None = None,
    system_prompt: str | None = None,
) -> StreamResult:
    """Async handler for streaming agent response."""
    from langgraph.errors import GraphRecursionError

    from clanker.agent import create_agent_graph_async
    from clanker.ui.chat_log import MessageType

    # Track active console and callbacks
    old_console = getattr(_local_state, "active_console", None)
    _local_state.active_console = console

    old_notify = get_notify_callback()
    old_ask = get_ask_callback()
    old_approval = get_approval_callback()

    # Get Textual app reference if available
    textual_app = getattr(console, "_textual_app", None)

    # Create graph inside async context
    graph, mcp_client = await create_agent_graph_async(
        settings, checkpointer, tools=tools, middleware=middleware, system_prompt=system_prompt
    )

    current_response = ""
    current_thinking = ""
    shown_tool_calls: set[str] = set()
    current_model_run: str | None = None
    thinking_shown = False
    in_think_tag = False
    think_tag_closed = False

    # Track TUI tool state per run_id for debounced loading indicators
    from clanker.ui.chat_log import ToolEntry
    _tui_tool_pending: dict[str, dict] = {}  # run_id -> {name, args}
    _tui_tool_entries: dict[str, ToolEntry] = {}  # run_id -> mounted entry (after debounce fires)
    _tui_debounce_tasks: dict[str, asyncio.Task] = {}  # run_id -> debounce task

    # Loading state
    first_content_received = False

    # Summarization detection
    model_call_count = 0
    tools_started = False
    summarization_detected = False
    summarization_spinner_shown = False

    # Debounced tool loader: mounts LoadingIndicator after delay if tool still running
    async def _tool_debounce(run_id: str, tool_name: str, args: str) -> None:
        await asyncio.sleep(0.2)
        if run_id in _tui_tool_pending and run_id not in _tui_tool_entries:
            # Tool still running after 200ms — show loader
            try:
                chat_log = textual_app.get_chat_log()
                entry = chat_log.add_tool_start(tool_name, args)
                _tui_tool_entries[run_id] = entry
            except Exception:
                pass
            finally:
                _tui_tool_pending.pop(run_id, None)
                _tui_debounce_tasks.pop(run_id, None)

    # Token tracking
    last_input_tokens = 0
    last_output_tokens = 0
    cumulative_output_tokens = 0
    last_cache_read_tokens = 0
    last_cache_creation_tokens = 0
    model_name = ""

    def _update_loading(message: str) -> None:
        """Update loading indicator in TUI."""
        if textual_app:
            try:
                status_bar = textual_app.get_status_bar()
                status_bar.set_loading(message)
            except Exception:
                pass

    def _stop_loading() -> None:
        """Stop loading indicator."""
        if textual_app:
            try:
                status_bar = textual_app.get_status_bar()
                status_bar.clear()
            except Exception:
                pass

    def _start_loading(message: str | None = None) -> None:
        """Start loading indicator."""
        if textual_app:
            msg = message or console.get_loading_message()
            _update_loading(msg)

    # Unified tool display handler
    tool_handler = ToolDisplayHandler(
        console=console,
        show_tool_calls=settings.output.show_tool_calls,
        on_tool_start=_stop_loading,
        on_tool_end=_start_loading,
    )

    # Register notify callback
    _pending_notifies: list[tuple[str, str, str | None]] = []

    def _notify_callback(message: str, level: str, title: str | None = None) -> None:
        console.print_notify(message, level, title)
        # Buffer notify messages — flush on next event loop iteration
        _pending_notifies.append((message, level, title))

    set_notify_callback(_notify_callback)

    # Register ask callback
    def _ask_callback(question, options, *, multi_select, allow_other, allow_cancel):
        from clanker.ui.prompts import select_options

        _stop_loading()
        with suppress(Exception):
            tool_handler.finalize_live()
        try:
            return select_options(
                question,
                options,
                multi_select=multi_select,
                allow_other=allow_other,
                allow_cancel=allow_cancel,
            )
        finally:
            _start_loading()

    set_ask_callback(_ask_callback)

    # Register approval callback
    def _approval_callback(question, options, *, preface=None):
        from clanker.ui.prompts import select_options

        _stop_loading()
        with suppress(Exception):
            tool_handler.finalize_live()
        try:
            return select_options(
                question,
                options,
                allow_other=False,
                allow_cancel=False,
                preface=preface,
            )
        finally:
            _start_loading()

    set_approval_callback(_approval_callback)

    try:
        _start_loading()

        stream_config = {**config, "recursion_limit": settings.context.max_agent_steps}

        await _heal_orphaned_tool_calls(graph, config)

        with _suppress_subprocess_stderr():
            async for event in graph.astream_events(
                state, config=stream_config, version="v2"
            ):
                # Flush buffered notify messages from callback
                if _pending_notifies and textual_app:
                    try:
                        chat_log = textual_app.get_chat_log()
                        for msg, level, title in _pending_notifies:
                            if msg:
                                chat_log.add_message(msg, MessageType.NOTIFY, title=level)
                    except Exception:
                        pass
                    _pending_notifies.clear()

                event_type = event.get("event", "")

                if _interrupted:
                    _stop_loading()
                    tool_handler.finalize_live()
                    if textual_app:
                        try:
                            chat_log = textual_app.get_chat_log()
                            chat_log.add_message(
                                "*BZZZT* Agent halted. Control returned to you. *CLANK*",
                                MessageType.WARNING,
                            )
                        except Exception:
                            pass
                    return StreamResult(
                        response=current_response,
                        input_tokens=last_input_tokens,
                        output_tokens=last_output_tokens,
                        cache_read_tokens=last_cache_read_tokens,
                        cache_creation_tokens=last_cache_creation_tokens,
                        model_name=model_name,
                        summarization_occurred=summarization_detected,
                    )

                if event_type == "on_tool_start":
                    tools_started = True

                    if settings.output.show_tool_calls:
                        run_id = event.get("run_id", "")
                        if run_id and run_id not in shown_tool_calls:
                            shown_tool_calls.add(run_id)
                            tool_name_ev = event.get("name", "unknown")
                            tool_input = event.get("data", {}).get("input", {})
                            if tool_name_ev == "run" and not is_yolo_mode():
                                continue
                            if tool_name_ev.lower() in ("notify", "ask_user", "spawn_subagent"):
                                continue

                            arg_str = _get_tool_arg_summary(tool_name_ev, tool_input)

                            if textual_app:
                                try:
                                    # Store pending tool info — debounce timer will
                                    # mount the LoadingIndicator if the tool takes >200ms
                                    _tui_tool_pending[run_id] = {
                                        "name": tool_name_ev,
                                        "args": arg_str,
                                    }
                                    # Schedule debounce: show loader after 200ms if still running
                                    task = asyncio.create_task(
                                        _tool_debounce(run_id, tool_name_ev, arg_str)
                                    )
                                    _tui_debounce_tasks[run_id] = task
                                except Exception:
                                    pass

                            tool_handler.handle_tool_start(tool_name_ev, tool_input)
                    else:
                        _stop_loading()

                elif event_type == "on_tool_end":
                    tool_name_end = event.get("name", "")
                    if tool_name_end.lower() in ("notify", "ask_user", "spawn_subagent"):
                        # Render notify output in TUI chat log from tool result
                        if tool_name_end.lower() == "notify" and textual_app:
                            try:
                                data = event.get("data", {})
                                raw_output = data.get("output", {})
                                if isinstance(raw_output, dict):
                                    msg = raw_output.get("message", "")
                                    level = raw_output.get("level", "info")
                                elif isinstance(raw_output, str):
                                    import json as _json
                                    parsed = _json.loads(raw_output) if raw_output.strip() else {}
                                    msg = parsed.get("message", "") if isinstance(parsed, dict) else raw_output
                                    level = parsed.get("level", "info") if isinstance(parsed, dict) else "info"
                                else:
                                    msg, level = "", "info"
                                if msg:
                                    chat_log = textual_app.get_chat_log()
                                    chat_log.add_message(msg, MessageType.NOTIFY, title=level)
                            except Exception:
                                pass
                        _start_loading()
                        continue

                    if settings.output.show_tool_calls:
                        data = event.get("data", {})
                        tool_output = normalize_tool_output(data.get("output"))
                        tool_handler.handle_tool_end(tool_name_end, tool_output)

                        if textual_app:
                            try:
                                chat_log = textual_app.get_chat_log()
                                is_error = console._is_failed_tool_result(
                                    tool_output, tool_name_end,
                                    tool_handler._pending_inputs[0][2] if tool_handler._pending_inputs else None
                                ) if tool_handler._pending_inputs else False

                                run_id_end = event.get("run_id", "")

                                # Cancel debounce task if tool finished before it fired
                                debounce_task = _tui_debounce_tasks.pop(run_id_end, None)
                                if debounce_task is not None and not debounce_task.done():
                                    debounce_task.cancel()
                                    # Suppress CancelledError — consume it in the next await
                                    try:
                                        await debounce_task
                                    except asyncio.CancelledError:
                                        pass

                                # Check if debounce timer already mounted a loader
                                existing_entry = _tui_tool_entries.pop(run_id_end, None)
                                pending_info = _tui_tool_pending.pop(run_id_end, None)

                                if existing_entry is not None:
                                    # Loader was already showing — replace with result
                                    chat_log.update_tool_end(
                                        existing_entry, tool_output, success=not is_error
                                    )
                                elif pending_info is not None:
                                    # Tool finished before debounce fired — show as instant complete
                                    chat_log.add_tool_complete(
                                        pending_info["name"],
                                        pending_info["args"],
                                        tool_output,
                                        success=not is_error,
                                    )
                                else:
                                    # Fallback: no tracking info available
                                    tool_input_end = event.get("data", {}).get("input", {})
                                    arg_str_end = _get_tool_arg_summary(tool_name_end, tool_input_end)
                                    chat_log.add_tool_complete(
                                        tool_name_end, arg_str_end, tool_output,
                                        success=not is_error,
                                    )
                            except Exception:
                                pass
                    else:
                        tool_handler.clear_tool_tracking(tool_name_end)
                        _start_loading()

                elif event_type == "on_chat_model_start":
                    run_id = event.get("run_id", "")
                    if run_id != current_model_run:
                        model_call_count += 1

                        if model_call_count == 2 and not tools_started and not summarization_spinner_shown:
                            summarization_detected = True
                            summarization_spinner_shown = True
                            _stop_loading()
                            console.print_info("*WHIRR* Compressing memory banks...")
                            _start_loading()

                        if tool_handler.has_pending_tools():
                            tool_handler.flush_pending_tools()
                        current_response = ""
                        current_thinking = ""
                        thinking_shown = False
                        first_content_received = False
                        in_think_tag = False
                        think_tag_closed = False
                        current_model_run = run_id

                elif event_type == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk:
                        content = getattr(chunk, "content", None)

                        if content and not first_content_received:
                            first_content_received = True
                            _stop_loading()

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

                        elif content and isinstance(content, str):
                            remaining = content
                            while remaining:
                                if think_tag_closed:
                                    current_response += remaining
                                    remaining = ""
                                elif in_think_tag:
                                    end_idx = remaining.find("</think>")
                                    if end_idx != -1:
                                        current_thinking += remaining[:end_idx]
                                        remaining = remaining[end_idx + 8:]
                                        in_think_tag = False
                                        think_tag_closed = True
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
                                        if not thinking_shown and current_thinking:
                                            console.print_thinking_start()
                                            thinking_shown = True
                                    else:
                                        current_thinking += remaining
                                        if not thinking_shown:
                                            console.print_thinking_start()
                                            thinking_shown = True
                                        remaining = ""

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
        _stop_loading()
        if textual_app:
            with suppress(Exception):
                textual_app.get_chat_log().add_message(
                    f"Operation cancelled: {e}", MessageType.WARNING
                )
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
        _stop_loading()
        tool_handler.finalize_live()
        limit = settings.context.max_agent_steps
        if textual_app:
            with suppress(Exception):
                textual_app.get_chat_log().add_message(
                    f"*WHIRR* Hit step limit ({limit} steps). Say 'continue' to resume, "
                    f"or raise context.max_agent_steps in config.",
                    MessageType.WARNING,
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
        _stop_loading()
        if textual_app:
            with suppress(Exception):
                textual_app.get_chat_log().add_message(
                    "*BZZZT* Agent halted. *CLANK*", MessageType.WARNING
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

    except Exception as exc:  # noqa: BLE001
        from clanker.context import is_context_length_error

        if not is_context_length_error(exc):
            raise

        _stop_loading()
        tool_handler.finalize_live()
        await _compact_oversized_tool_call_args(graph, config, settings)
        if textual_app:
            with suppress(Exception):
                textual_app.get_chat_log().add_message(
                    "*CLANK* Request too large. Trimmed bulky bits — try again.",
                    MessageType.ERROR,
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
        set_notify_callback(old_notify)
        set_ask_callback(old_ask)
        set_approval_callback(old_approval)
        _local_state.active_console = old_console

    # If we buffered thinking but never saw </think>, treat as response
    if current_thinking and not think_tag_closed and not current_response:
        current_response = current_thinking
        current_thinking = ""

    # Print final response
    if current_response.strip():
        console.print_assistant_message(current_response)
        if textual_app:
            with suppress(Exception):
                textual_app.get_chat_log().add_message(
                    current_response, MessageType.ASSISTANT
                )

    if current_thinking:
        console.print_thinking(current_thinking)
        if textual_app:
            with suppress(Exception):
                textual_app.get_chat_log().add_message(
                    current_thinking, MessageType.THINKING
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


def stream_agent_response_sync(
    settings: Settings,
    checkpointer,
    state: dict,
    config: dict,
    console,
    tools: list | None = None,
    middleware: list | None = None,
    system_prompt: str | None = None,
) -> StreamResult:
    """Synchronous wrapper for async stream_agent_response."""
    global _current_streaming_task, _interrupted
    _interrupted = False

    original_handler = None
    try:
        original_handler = signal.getsignal(signal.SIGINT)
        def _sigint_handler(signum, frame):
            _cancel_streaming_task()
        signal.signal(signal.SIGINT, _sigint_handler)
    except ValueError:
        pass

    try:
        try:
            active_loop = asyncio.get_running_loop()
        except RuntimeError:
            active_loop = None

        is_main_thread = threading.current_thread() is threading.main_thread()

        if active_loop is not None and active_loop.is_running():
            coro = stream_agent_response_async(
                settings, checkpointer, state, config, console,
                tools=tools, middleware=middleware, system_prompt=system_prompt
            )

            if is_main_thread:
                res_container = []
                def run_isolated():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        res = new_loop.run_until_complete(
                            stream_agent_response_async(
                                settings, checkpointer, state, config, console,
                                tools=tools, middleware=middleware, system_prompt=system_prompt
                            )
                        )
                        res_container.append(res)
                    except Exception as e:
                        res_container.append(e)
                    finally:
                        new_loop.close()
                t = threading.Thread(target=run_isolated)
                t.start()
                t.join()
                if res_container and isinstance(res_container[0], Exception):
                    raise res_container[0]
                return res_container[0] if res_container else StreamResult(response="")
            else:
                future = asyncio.run_coroutine_threadsafe(coro, active_loop)
                return future.result()

        loop = _get_or_create_loop()
        _current_streaming_task = loop.create_task(
            stream_agent_response_async(
                settings, checkpointer, state, config, console,
                tools=tools, middleware=middleware, system_prompt=system_prompt
            )
        )
        return loop.run_until_complete(_current_streaming_task)
    except asyncio.CancelledError:
        return StreamResult(response="")
    except KeyboardInterrupt:
        _cancel_streaming_task()
        return StreamResult(response="")
    finally:
        _current_streaming_task = None
        if original_handler is not None:
            with suppress(ValueError):
                signal.signal(signal.SIGINT, original_handler)
