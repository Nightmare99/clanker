"""Unified tool display handling for all providers."""

from typing import Callable


class ToolDisplayHandler:
    """Handles tool call and result display consistently across providers."""

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

    def _make_tool_key(self, tool_name: str, tool_input: dict) -> str:
        """Create a unique key for a tool call to detect duplicates."""
        # Use tool name + hash of sorted input items for uniqueness
        input_str = str(sorted(tool_input.items())) if tool_input else ""
        return f"{tool_name}:{hash(input_str)}"

    def _is_display_only_tool(self, tool_name: str) -> bool:
        """Return True for tools that handle their own console output."""
        return tool_name in self._DISPLAY_ONLY_TOOLS

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

    def handle_tool_start(self, tool_name: str, tool_input: dict) -> None:
        """Handle tool start event from Copilot callback."""
        # Mark that Copilot callback is handling tools (skip LangGraph events)
        self._copilot_callback_active = True
        if self._on_tool_start:
            self._on_tool_start()
        if self._is_display_only_tool(tool_name):
            return
        # Force show even if duplicate detection would skip (callback is authoritative)
        self.show_tool(tool_name, tool_input, force=True)

    def handle_tool_end(self, tool_name: str, result: str) -> None:
        """Handle tool end event - display result and call on_tool_end callback."""
        if self._is_display_only_tool(tool_name):
            self.clear_tool_tracking(tool_name)
            if self._on_tool_end:
                self._on_tool_end()
            return
        # Force show even if duplicate detection would skip (callback is authoritative)
        self.show_tool_result(tool_name, result, force=True)
        # Clear tracking for this tool so it can be called again
        self.clear_tool_tracking(tool_name)
        if self._on_tool_end:
            self._on_tool_end()

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
