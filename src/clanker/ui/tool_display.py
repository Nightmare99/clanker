"""Unified tool display handling for all providers."""

from dataclasses import dataclass
from typing import Callable

from rich.console import Group
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text


@dataclass
class PendingToolCall:
    """A tool call waiting for its result."""
    tool_id: str
    tool_name: str
    tool_input: dict


class ToolDisplayHandler:
    """Handles tool call and result display consistently across providers.

    Uses a Live display to show pending tools with spinners, then prints
    the final result when each tool completes. This ensures tool headers
    and results are always displayed together, even with parallel execution.
    """

    # Tools that handle their own display - check case-insensitively
    _DISPLAY_ONLY_TOOLS = {"notify"}

    def __init__(
        self,
        console,
        show_tool_calls: bool = True,
        on_tool_start: Callable[[], None] | None = None,
        on_tool_end: Callable[[], None] | None = None,
    ):
        """Initialize the tool display handler.

        Args:
            console: Console instance for output.
            show_tool_calls: Whether to display tool calls.
            on_tool_start: Callback when tool display starts (e.g., stop spinner).
            on_tool_end: Callback when tool display ends (e.g., start spinner).
        """
        self._console = console
        self._show_tool_calls = show_tool_calls
        self._on_tool_start = on_tool_start
        self._on_tool_end = on_tool_end
        self._pending_tools: list[tuple[str, dict]] = []
        # Track displayed tools to prevent duplicates (Copilot callback + LangGraph events)
        self._active_tools: set[str] = set()  # Tool names currently being executed
        self._shown_results: set[str] = set()  # Tool names whose results were shown
        # Track tool inputs for result display (needed when SDK strips fields like 'path')
        self._pending_inputs: list[tuple[str, dict]] = []  # Queue of (tool_name, input) for matching results
        # Flag to indicate Copilot callback is handling tools (skip LangGraph events)
        self._copilot_callback_active: bool = False

        # Live display for pending tools (Copilot SDK mode)
        self._live: Live | None = None
        self._pending_calls: dict[str, PendingToolCall] = {}  # tool_id -> PendingToolCall
        self._pending_order: list[str] = []  # Insertion order
        self._tool_id_counter: int = 0  # For generating unique IDs

    def _make_tool_key(self, tool_name: str, tool_input: dict) -> str:
        """Create a unique key for a tool call to detect duplicates."""
        # Use tool name + hash of sorted input items for uniqueness
        input_str = str(sorted(tool_input.items())) if tool_input else ""
        return f"{tool_name}:{hash(input_str)}"

    def _is_display_only_tool(self, tool_name: str) -> bool:
        """Return True for tools that handle their own console output."""
        return tool_name.lower() in self._DISPLAY_ONLY_TOOLS

    def show_tool(self, tool_name: str, tool_input: dict, force: bool = False) -> bool:
        """Display a single tool call with details.

        Handles special cases for edit_file, write_file, append_file
        to show diffs and content previews.

        Returns True if the tool was displayed, False if skipped (duplicate).
        """
        if not self._show_tool_calls:
            return False

        # Skip if Copilot callback is handling tools (unless forced by callback itself)
        if self._copilot_callback_active and not force:
            return False

        # Some tools render their own user-facing output and should not also
        # show the generic tool header line.
        if self._is_display_only_tool(tool_name):
            return False

        # Check for duplicate (unless forced)
        tool_key = self._make_tool_key(tool_name, tool_input)
        if not force and tool_key in self._active_tools:
            return False
        self._active_tools.add(tool_key)

        self._console.print_tool_use(tool_name, tool_input)

        # Store input for result display (needed when SDK strips fields)
        self._pending_inputs.append((tool_name, tool_input))

        # Special handling for file modification tools
        if tool_name == "edit_file":
            old_str = tool_input.get("old_string", "")
            new_str = tool_input.get("new_string", "")
            if old_str or new_str:
                self._console.print_edit_diff(old_str, new_str)
        elif tool_name == "write_file":
            content = tool_input.get("content", "")
            if content:
                self._console.print_write_content(content, is_append=False)
        elif tool_name == "append_file":
            content = tool_input.get("content", "")
            if content:
                self._console.print_write_content(content, is_append=True)

        return True

    def show_tool_result(self, tool_name: str, result: str, force: bool = False) -> bool:
        """Display a tool result.

        Returns True if result was displayed, False if skipped (duplicate).
        """
        if not self._show_tool_calls:
            return False

        # Skip if Copilot callback is handling tools (unless forced by callback itself)
        if self._copilot_callback_active and not force:
            return False

        # Some tools already printed their user-facing result directly.
        if self._is_display_only_tool(tool_name):
            return False

        # Try to get tool name from pending inputs if SDK sent "unknown"
        matched_name = tool_name
        if (tool_name == "unknown" or tool_name == "") and self._pending_inputs:
            matched_name = self._pending_inputs[0][0]  # Use name from first pending
            self._pending_inputs.pop(0)
        elif self._pending_inputs:
            # Pop one entry to keep queue in sync (even if we don't use it)
            self._pending_inputs.pop(0)

        # Use result hash for duplicate detection (handles multiple same-name tools)
        result_key = f"{matched_name}:{hash(result)}"
        if result_key in self._shown_results:
            return False
        self._shown_results.add(result_key)

        # Let print_tool_result extract path from result JSON (more reliable than input matching)
        if result and result.strip():
            self._console.print_tool_result(result, tool_name=matched_name, tool_input=None)

        return True

    def clear_tool_tracking(self, tool_name: str = None) -> None:
        """Clear tracking for a tool (call after tool completes).

        If tool_name is None, clears all tracking.
        """
        if tool_name is None:
            self._active_tools.clear()
            self._shown_results.clear()
        else:
            # Remove entries containing this tool name
            self._active_tools = {k for k in self._active_tools if not k.startswith(f"{tool_name}:")}
            self._shown_results.discard(tool_name)

    def queue_tool(self, tool_name: str, tool_input: dict) -> None:
        """Queue a tool call for batch display (parallel tools).

        Skips if tool was already shown (e.g., by Copilot callback).
        """
        tool_key = self._make_tool_key(tool_name, tool_input)
        if tool_key in self._active_tools:
            return  # Already shown by another path
        self._pending_tools.append((tool_name, tool_input))

    def flush_pending_tools(self) -> None:
        """Display any pending tool calls."""
        if not self._pending_tools:
            return

        if not self._show_tool_calls:
            self._pending_tools = []
            return

        if len(self._pending_tools) > 1:
            # Mark all as shown before displaying
            for name, args in self._pending_tools:
                self._active_tools.add(self._make_tool_key(name, args))
            self._console.print_parallel_tools(self._pending_tools)
        else:
            self.show_tool(*self._pending_tools[0])

        self._pending_tools = []

    def has_pending_tools(self) -> bool:
        """Check if there are pending tools to display."""
        return len(self._pending_tools) > 0

    def _format_tool_header_text(self, tool_name: str, tool_input: dict) -> Text:
        """Format a tool header as Rich Text for Live display."""
        text = Text()
        text.append("  > ", style="dim")
        args = tool_input or {}

        if tool_name == "read_file":
            text.append("Read ", style="magenta")
            text.append(args.get("file_path", "file"), style="cyan")
        elif tool_name == "write_file":
            text.append("Write ", style="magenta")
            text.append(args.get("file_path", "file"), style="cyan")
        elif tool_name == "edit_file":
            text.append("Edit ", style="magenta")
            text.append(args.get("file_path", "file"), style="cyan")
        elif tool_name == "execute_shell":
            cmd = (args.get("command", "") or "")[:60]
            text.append(f"Run: {cmd}", style="magenta")
        elif tool_name == "glob_search":
            text.append("Find ", style="magenta")
            text.append(args.get("pattern", "*"), style="cyan")
        elif tool_name == "grep_search":
            text.append("Search ", style="magenta")
            text.append((args.get("pattern", "") or "")[:40], style="cyan")
        elif tool_name == "list_directory":
            text.append("List ", style="magenta")
            text.append(args.get("path", "."), style="cyan")
        else:
            text.append(tool_name, style="magenta")

        return text

    def _render_pending_live(self) -> Group:
        """Render pending tools with spinners for Live display."""
        items = []
        for tool_id in self._pending_order:
            if tool_id not in self._pending_calls:
                continue
            call = self._pending_calls[tool_id]
            header = self._format_tool_header_text(call.tool_name, call.tool_input)
            header.append(" ", style="dim")
            items.append(header)
            items.append(Spinner("dots", style="dim cyan"))
            items.append(Text("\n"))
        return Group(*items) if items else Text("")

    def _update_live_display(self) -> None:
        """Update or create the Live display for pending tools."""
        if not self._pending_calls:
            if self._live:
                self._live.stop()
                self._live = None
            return

        if self._live is None:
            self._live = Live(
                self._render_pending_live(),
                console=self._console._console,
                refresh_per_second=10,
                transient=True,
            )
            self._live.start()
        else:
            self._live.update(self._render_pending_live())

    def handle_tool_start(self, tool_name: str, tool_input: dict) -> None:
        """Handle tool start event from Copilot callback.

        Adds tool to pending display with a spinner. The actual header + result
        will be printed together when handle_tool_end is called.
        """
        self._copilot_callback_active = True
        if self._on_tool_start:
            self._on_tool_start()
        if self._is_display_only_tool(tool_name):
            return
        if not self._show_tool_calls:
            return

        # Generate unique ID for this tool call
        self._tool_id_counter += 1
        tool_id = f"{tool_name}:{self._tool_id_counter}"

        # Add to pending
        self._pending_calls[tool_id] = PendingToolCall(
            tool_id=tool_id,
            tool_name=tool_name,
            tool_input=tool_input,
        )
        self._pending_order.append(tool_id)

        # Store input for result matching
        self._pending_inputs.append((tool_id, tool_name, tool_input))

        # Update Live display
        self._update_live_display()

    def handle_tool_end(self, tool_name: str, result: str) -> None:
        """Handle tool end event - display header + result together.

        Removes tool from pending display and prints final output.
        """
        if self._is_display_only_tool(tool_name):
            self.clear_tool_tracking(tool_name)
            if self._on_tool_end:
                self._on_tool_end()
            return

        if not self._show_tool_calls:
            if self._on_tool_end:
                self._on_tool_end()
            return

        # Find matching pending tool
        tool_id = None
        tool_input = {}
        for i, (tid, tname, tinput) in enumerate(self._pending_inputs):
            if tname == tool_name:
                tool_id = tid
                tool_input = tinput
                self._pending_inputs.pop(i)
                break

        # Stop Live display before printing
        if self._live:
            self._live.stop()
            self._live = None

        # Print header + result together (permanent output)
        self._console.print_tool_use(tool_name, tool_input)

        # Show diffs for file modification tools
        if tool_name == "edit_file":
            old_str = tool_input.get("old_string", "")
            new_str = tool_input.get("new_string", "")
            if old_str or new_str:
                self._console.print_edit_diff(old_str, new_str)
        elif tool_name == "write_file":
            content = tool_input.get("content", "")
            if content:
                self._console.print_write_content(content, is_append=False)
        elif tool_name == "append_file":
            content = tool_input.get("content", "")
            if content:
                self._console.print_write_content(content, is_append=True)

        # Show result
        if result and result.strip():
            self._console.print_tool_result(result, tool_name=tool_name, tool_input=tool_input)

        # Remove from pending
        if tool_id and tool_id in self._pending_calls:
            del self._pending_calls[tool_id]
            if tool_id in self._pending_order:
                self._pending_order.remove(tool_id)

        # Restart Live display if there are still pending tools
        self._update_live_display()

        self.clear_tool_tracking(tool_name)
        if self._on_tool_end:
            self._on_tool_end()

    def finalize_live(self) -> None:
        """Stop the Live display and clean up pending state.

        Call this at the end of a response to ensure no stale displays remain.
        """
        if self._live:
            self._live.stop()
            self._live = None
        self._pending_calls.clear()
        self._pending_order.clear()
        self._pending_inputs.clear()

    def create_callback(self) -> Callable[[str, dict, str | None], None]:
        """Create a callback function for Copilot SDK tool events.

        Returns a function that can be registered with set_tool_call_callback.
        """
        def callback(tool_name: str, args: dict, result: str | None) -> None:
            if result is None:
                # Tool starting
                self.handle_tool_start(tool_name, args)
            else:
                # Tool completed
                self.handle_tool_end(tool_name, result)

        return callback


def normalize_tool_output(output) -> str:
    """Normalize tool output to a string for display.

    Single source of truth for tool output normalization across all providers.
    Handles: Copilot SDK Result objects, LangChain messages, dicts, strings, lists.
    """
    import ast
    import json

    if output is None:
        return ""

    # Handle Copilot SDK Result-like objects with special attributes
    if hasattr(output, 'text_result_for_llm'):
        return normalize_tool_output(output.text_result_for_llm)
    if hasattr(output, 'textResultForLlm'):
        return normalize_tool_output(output.textResultForLlm)

    # Handle LangChain message objects with .content
    if hasattr(output, "content") and not isinstance(output, (str, dict)):
        return normalize_tool_output(output.content)

    # Handle lists
    if isinstance(output, list):
        return "\n".join(str(item) for item in output)

    # If it's a string, try to parse as dict (JSON or Python literal)
    if isinstance(output, str):
        parsed = None
        try:
            parsed = json.loads(output)
        except (json.JSONDecodeError, ValueError):
            pass

        if parsed is None:
            try:
                parsed = ast.literal_eval(output)
            except (ValueError, SyntaxError):
                pass

        if isinstance(parsed, dict):
            output = parsed
        else:
            # Plain string, return as-is
            return output

    # Handle dict results - preserve full JSON for tool result handlers
    if isinstance(output, dict):
        # Check for error first
        if not output.get('ok', True) and 'error' in output:
            return f"Error: {output['error']}"

        # For structured tool results with 'ok' field, preserve full JSON
        # so print_tool_result handlers can extract what they need
        if 'ok' in output:
            return json.dumps(output)

        # Fallback - don't show raw dict, just indicate success/failure
        if output.get('ok', False):
            return "(completed)"
        return str(output)

    return str(output)
