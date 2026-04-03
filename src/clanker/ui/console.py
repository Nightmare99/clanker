"""Console output management using Rich."""

import json
import random
from contextlib import contextmanager

from rich.console import Console as RichConsole
from rich.panel import Panel
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.text import Text
from rich.markup import escape
from rich.theme import Theme
from rich.live import Live

from clanker.config import get_settings

# Clanker-themed loading messages
LOADING_MESSAGES = [
    "Warming up the vacuum tubes...",
    "Consulting the ancient algorithms...",
    "Spinning up the cogitators...",
    "Calibrating neural pathways...",
    "Rerouting through the mainframe...",
    "Engaging thought processors...",
    "Defragmenting the brain cores...",
    "Channeling the machine spirits...",
    "Overclocking the logic gates...",
    "Parsing the infinite datastream...",
    "Buffering consciousness...",
    "Aligning the servo motors...",
    "Charging the capacitors...",
    "Igniting the inference engine...",
    "Synchronizing neural networks...",
    "Booting secondary processors...",
    "Greasing the gears of thought...",
    "Untangling the wire spaghetti...",
    "Polishing the chrome neurons...",
    "Waking the dormant subroutines...",
    "Tuning the harmonic resonators...",
    "Compiling a witty response...",
    "Consulting the oracle circuits...",
    "Decrypting the cosmic noise...",
    "Assembling coherent thoughts...",
    "Running diagnostic protocols...",
    "Amplifying the signal...",
    "Traversing the decision tree...",
    "Recalibrating output filters...",
    "Synthesizing a response matrix...",
]

# Custom theme for Clanker
CLANKER_THEME = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "red bold",
    "success": "green",
    "tool": "magenta",
    "user": "blue bold",
    "assistant": "green",
})


class Console:
    """Rich console wrapper for Clanker output."""

    def __init__(self):
        """Initialize the console."""
        self._console = RichConsole(theme=CLANKER_THEME)
        self._settings = get_settings()

    @property
    def width(self) -> int:
        """Get console width."""
        return self._console.width

    def print(self, *args, **kwargs) -> None:
        """Print to console."""
        self._console.print(*args, **kwargs)

    def print_rich_text(self, text: str) -> None:
        """Print rich-text (markup) formatted text (no Markdown parsing)."""
        from clanker.ui.markup_adapter import markdown_to_rich

        rich_text = Text.from_markup(markdown_to_rich(text))
        self._console.print(rich_text)

    def print_code(self, code: str, language: str = "python") -> None:
        """Print syntax-highlighted code."""
        if self._settings.output.syntax_highlighting:
            syntax = Syntax(code, language, theme="monokai", line_numbers=True)
            self._console.print(syntax)
        else:
            self._console.print(code)

    def print_user_message(self, message: str) -> None:
        """Print a user message."""
        self._console.print(Text("You: ", style="user"), end="")
        self._console.print(message)

    def print_assistant_message(self, message: str) -> None:
        """Print an assistant message using rich text markup."""
        self.print_rich_text(message)

    def print_tool_call(self, tool_name: str, args: dict | None = None) -> None:
        """Print a tool call indicator (detailed version)."""
        if not self._settings.output.show_tool_calls:
            return

        text = Text()
        text.append("[", style="dim")
        text.append(tool_name, style="tool")
        if args:
            args_str = ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:2])
            if len(args) > 2:
                args_str += ", ..."
            text.append(f"({args_str})", style="dim")
        text.append("]", style="dim")
        self._console.print(text)

    def _shorten_path(self, path: str, max_parts: int = 3) -> str:
        """Shorten a file path to show last N components."""
        parts = path.rstrip("/").split("/")
        if len(parts) <= max_parts:
            return path
        return ".../" + "/".join(parts[-max_parts:])

    def _truncate(self, text: str, max_len: int = 50) -> str:
        """Truncate text with ellipsis if too long."""
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    def print_tool_use(self, tool_name: str, args: dict | None = None) -> None:
        """Print a concise, user-friendly tool usage message."""
        if not self._settings.output.show_tool_calls:
            return

        args = args or {}
        text = Text()
        text.append("  > ", style="dim")

        # Format based on tool type for user-friendly output
        if tool_name == "read_file":
            path = args.get("file_path", "")
            if path:
                text.append("Read ", style="tool")
                text.append(path, style="cyan")
            else:
                text.append("Read file", style="tool")

        elif tool_name == "write_file":
            path = args.get("file_path", "")
            if path:
                text.append("Write ", style="tool")
                text.append(path, style="cyan")
            else:
                text.append("Write file", style="tool")

        elif tool_name == "edit_file":
            path = args.get("file_path", "")
            if path:
                text.append("Edit ", style="tool")
                text.append(path, style="cyan")
            else:
                text.append("Edit file", style="tool")

        elif tool_name == "append_file":
            path = args.get("file_path", "")
            if path:
                text.append("Append ", style="tool")
                text.append(path, style="cyan")
            else:
                text.append("Append file", style="tool")

        elif tool_name == "bash":
            cmd = self._truncate(args.get("command", ""), 60)
            text.append(f"Run: {cmd}", style="tool")

        elif tool_name == "glob_search":
            pattern = args.get("pattern", "*")
            path = args.get("path", "")
            text.append("Find ", style="tool")
            text.append(pattern, style="cyan")
            if path and path != ".":
                text.append(" in ", style="dim")
                text.append(path, style="cyan")

        elif tool_name == "grep_search":
            pattern = args.get("pattern", "")
            path = args.get("path", "")
            text.append("Search ", style="tool")
            text.append(self._truncate(pattern, 40), style="cyan")
            if path and path != ".":
                text.append(" in ", style="dim")
                text.append(path, style="cyan")

        elif tool_name == "list_directory":
            path = args.get("path", ".")
            text.append("List ", style="tool")
            text.append(path, style="cyan")

        else:
            # Handle MCP tools and other unknown tools
            # MCP tools often have format "server__tool" or "mcp_server_tool"
            display_name = tool_name

            # Check if it looks like an MCP tool (contains double underscore or mcp prefix)
            if "__" in tool_name:
                parts = tool_name.split("__", 1)
                server_name = parts[0]
                actual_tool = parts[1] if len(parts) > 1 else tool_name
                text.append(f"[{server_name}] ", style="cyan")
                display_name = actual_tool

            text.append(display_name, style="tool")

            # Show first meaningful arg value
            if args:
                # Try to find a meaningful arg to display
                display_val = None
                for key in ["query", "path", "url", "input", "text", "command", "name"]:
                    if key in args:
                        display_val = str(args[key])
                        break
                if display_val is None and args:
                    display_val = str(list(args.values())[0])
                if display_val:
                    text.append(f": {self._truncate(display_val, 40)}", style="dim")

        self._console.print(text)

    def _parse_tool_json(self, result: str) -> dict | None:
        """Try to parse a tool result as JSON. Returns None if not valid JSON."""
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    def _print_dim(self, text_str: str) -> None:
        """Print a short dim/muted line with indent."""
        text = Text()
        text.append("    ", style="dim")
        text.append(text_str, style="dim")
        self._console.print(text)

    def print_tool_result(self, result: str, tool_name: str = "", max_lines: int = 4, max_chars: int = 300) -> None:
        """Print a smart, per-tool summary of a tool result in muted grey."""
        if not self._settings.output.show_tool_calls:
            return

        result = result.strip()
        if not result:
            return

        # ── Tools whose output is already shown as a diff / content block ──────
        # write_file, append_file, edit_file: diff already printed above the result
        if tool_name in ("write_file", "append_file", "edit_file"):
            return

        parsed = self._parse_tool_json(result)

        # ── read_file: show the actual file content, not the JSON wrapper ───────
        if tool_name == "read_file":
            if parsed and parsed.get("ok"):
                content = parsed.get("content", "")
                if not content:
                    return
                lines = content.splitlines()
                preview_lines = lines[:max_lines]
                preview = "\n".join(preview_lines)
                if len(preview) > max_chars:
                    preview = preview[:max_chars] + "…"
                suffix = f" (+{len(lines) - max_lines} lines)" if len(lines) > max_lines else ""
                self._print_dim(preview + suffix)
            elif parsed and not parsed.get("ok"):
                self._print_dim(str(parsed.get("message", result))[:max_chars])
            return

        # ── bash: show stdout/stderr trimmed ────────────────────────────────────
        if tool_name == "bash":
            if parsed:
                # bash tool returns {"ok": bool, "output": "...", ...}
                output = parsed.get("output", "") or parsed.get("stdout", "") or parsed.get("stderr", "")
            else:
                output = result
            output = output.strip()
            if not output:
                return
            lines = output.splitlines()
            preview = "\n".join(lines[:max_lines])
            if len(preview) > max_chars:
                preview = preview[:max_chars] + "…"
            suffix = f" (+{len(lines) - max_lines} lines)" if len(lines) > max_lines else ""
            self._print_dim(preview + suffix)
            return

        # ── glob_search: "N files found" ────────────────────────────────────────
        if tool_name == "glob_search":
            if parsed and parsed.get("ok"):
                files = parsed.get("files", parsed.get("results", []))
                n = len(files) if isinstance(files, list) else 0
                if n == 0:
                    self._print_dim("No files found")
                elif n == 1:
                    self._print_dim(str(files[0]))
                else:
                    self._print_dim(f"{n} files found — {files[0]}, {files[1]}" + (", …" if n > 2 else ""))
            return

        # ── grep_search: "N matches" ─────────────────────────────────────────────
        if tool_name == "grep_search":
            if parsed and parsed.get("ok"):
                matches = parsed.get("matches", parsed.get("results", []))
                n = len(matches) if isinstance(matches, list) else 0
                if n == 0:
                    self._print_dim("No matches")
                else:
                    self._print_dim(f"{n} match{'es' if n != 1 else ''}")
            return

        # ── list_directory: "N items" ────────────────────────────────────────────
        if tool_name == "list_directory":
            if parsed and parsed.get("ok"):
                items = parsed.get("items", [])
                n = len(items) if isinstance(items, list) else 0
                self._print_dim(f"{n} item{'s' if n != 1 else ''}")
            return

        # ── memory tools ─────────────────────────────────────────────────────────
        if tool_name == "remember":
            if parsed and parsed.get("ok"):
                mem_id = parsed.get("memory_id", "")
                self._print_dim(f"Saved{f' ({mem_id})' if mem_id else ''}")
            return

        if tool_name == "recall":
            if parsed and parsed.get("ok"):
                count = parsed.get("count", 0)
                self._print_dim(f"{count} memor{'ies' if count != 1 else 'y'} found")
            return

        if tool_name == "forget":
            if parsed and parsed.get("ok"):
                self._print_dim("Memory deleted")
            return

        if tool_name == "list_memories":
            if parsed and parsed.get("ok"):
                count = parsed.get("count", 0)
                self._print_dim(f"{count} memor{'ies' if count != 1 else 'y'}")
            return

        # ── fallback: raw truncated output (MCP tools, etc.) ────────────────────
        lines = result.split('\n')
        if len(lines) > max_lines:
            display = '\n'.join(lines[:max_lines])
            suffix = f"  … (+{len(lines) - max_lines} lines)"
        else:
            display = result
            suffix = ""
        if len(display) > max_chars:
            display = display[:max_chars] + "…"
            suffix = ""
        text = Text()
        text.append("    ", style="dim")
        text.append(display.replace('\n', '\n    '), style="dim")
        if suffix:
            text.append(suffix, style="dim italic")
        self._console.print(text)

    def print_edit_diff(self, old_string: str, new_string: str) -> None:
        """Print a diff showing what was changed in an edit operation."""
        if not self._settings.output.show_tool_calls:
            return

        # Truncate long strings for display
        max_len = 200
        old_display = old_string if len(old_string) <= max_len else old_string[:max_len] + "..."
        new_display = new_string if len(new_string) <= max_len else new_string[:max_len] + "..."

        text = Text()
        text.append("    - ", style="red")
        text.append(escape(old_display), style="red")
        self._console.print(text)

        text = Text()
        text.append("    + ", style="green")
        text.append(escape(new_display), style="green")
        self._console.print(text)

    def print_write_content(self, content: str, is_append: bool = False) -> None:
        """Print a preview of content being written to a file."""
        if not self._settings.output.show_tool_calls:
            return

        # Show first few lines of content
        lines = content.split("\n")
        max_lines = 5
        max_line_len = 80

        prefix = "    >> " if is_append else "    + "
        style = "cyan" if is_append else "green"

        for i, line in enumerate(lines[:max_lines]):
            display_line = line if len(line) <= max_line_len else line[:max_line_len] + "..."
            text = Text()
            text.append(prefix, style="dim")
            text.append(escape(display_line), style=style)
            self._console.print(text)

        if len(lines) > max_lines:
            remaining = len(lines) - max_lines
            self._console.print(Text(f"    ... ({remaining} more lines)", style="dim"))

    def print_thinking(self, thinking: str) -> None:
        """Print thinking/reasoning content."""
        # Truncate for display
        max_len = 500
        display = thinking[:max_len] + "..." if len(thinking) > max_len else thinking

        text = Text()
        text.append("  💭 ", style="dim")
        text.append(display, style="dim italic")
        self._console.print(text)

    def print_thinking_start(self) -> None:
        """Print indicator that thinking has started."""
        text = Text()
        text.append("  💭 ", style="dim")
        text.append("Thinking...", style="dim italic")
        self._console.print(text)

    def print_parallel_tools(self, tools: list[tuple[str, dict]]) -> None:
        """Print multiple tool calls happening in parallel."""
        text = Text()
        text.append("  ⚡ ", style="yellow")
        text.append(f"Running {len(tools)} tools in parallel:", style="dim")
        self._console.print(text)
        for tool_name, args in tools:
            self.print_tool_use(tool_name, args)

    def print_error(self, message: str) -> None:
        """Print an error message."""
        self._console.print(Text(f"Error: {message}", style="error"))

    def print_warning(self, message: str) -> None:
        """Print a warning message."""
        self._console.print(Text(f"Warning: {message}", style="warning"))

    def print_info(self, message: str) -> None:
        """Print an info message."""
        self._console.print(Text(message, style="info"))

    def print_update_available(self, message: str) -> None:
        """Print an update available notification."""
        self._console.print()
        self._console.print(Text("  [Update Available]", style="bold yellow"))
        for line in message.split("\n"):
            self._console.print(Text(f"  {line}", style="yellow"))
        self._console.print()

    def print_notify(self, message: str, level: str = "info") -> None:
        """Print an agent status notification (from the notify tool).

        Displayed inline while the agent is still executing so the user
        gets real-time progress feedback.

        Args:
            message: The status message sent by the agent.
            level: Severity / display style - "info", "success", "warning", "error".
        """
        level_styles = {
            "info": ("🔔", "cyan"),
            "success": ("✅", "green"),
            "warning": ("⚠️ ", "yellow"),
            "error": ("❌", "red bold"),
        }
        icon, style = level_styles.get(level, ("🔔", "cyan"))

        text = Text()
        text.append(f"  {icon} ", style="dim")
        text.append(message, style=style)
        self._console.print(text)

    def print_success(self, message: str) -> None:
        """Print a success message."""
        self._console.print(Text(message, style="success"))

    def print_panel(self, content: str, title: str = "", style: str = "blue") -> None:
        """Print content in a panel."""
        panel = Panel(content, title=title, border_style=style)
        self._console.print(panel)

    def print_welcome(self) -> None:
        """Print welcome message."""
        from clanker.config import get_default_model
        from clanker.runtime import is_yolo_mode

        agent_name = self._settings.agent.name

        # Get current model info
        current_model = get_default_model()
        if current_model:
            model_info = f"{current_model.name} [dim]({current_model.provider})[/dim]"
        else:
            model_info = "[dim]No model configured[/dim]"

        # Yolo mode indicator
        yolo_line = ""
        if is_yolo_mode():
            yolo_line = "\n  [bold yellow]YOLO MODE[/bold yellow] [dim]- bash commands auto-approved[/dim]"

        welcome = f"""
[bold cyan]
   █████████  █████       ██████   █████ █████   ████ ███████████  
  ███░░░░░███░░███       ░░██████ ░░███ ░░███   ███░ ░░███░░░░░███ 
 ███     ░░░  ░███        ░███░███ ░███  ░███  ███    ░███    ░███ 
░███          ░███        ░███░░███░███  ░███████     ░██████████  
░███          ░███        ░███ ░░██████  ░███░░███    ░███░░░░░███ 
░░███     ███ ░███      █ ░███  ░░█████  ░███ ░░███   ░███    ░███ 
 ░░█████████  ███████████ █████  ░░█████ █████ ░░████ █████   █████
  ░░░░░░░░░  ░░░░░░░░░░░ ░░░░░    ░░░░░ ░░░░░   ░░░░ ░░░░░   ░░░░░ 
[/bold cyan]

[dim]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/dim]
  Systems online. Circuits humming. Ready to build.
  Model: [bold cyan]{model_info}[/bold cyan]{yolo_line}
[dim]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/dim]

Commands:
  [dim]/model[/dim]    Switch model     [dim]/clear[/dim]    Clear history
  [dim]/history[/dim]  Past sessions    [dim]/memories[/dim] View memories
  [dim]/help[/dim]     Show help        [dim]/exit[/dim]     Power down

[bold green]>[/bold green] State your objective, human. [bold cyan]*CLANK*[/bold cyan]

"""
        self._console.print(welcome)

    def print_help(self) -> None:
        """Print help information."""
        help_text = """
[bold cyan]*WHIRR*[/bold cyan] [bold]CLANKER HELP SUBSYSTEM[/bold]

[bold]System Commands:[/bold]
  /help       Display this help matrix
  /clear      Wipe conversation memory banks
  /model      Query current AI model status
  /config     Display configuration parameters
  /mcp        Show MCP server connections
  /logs       Access diagnostic log files
  /gh-login   Authenticate with GitHub for Copilot
  /exit       Initiate shutdown sequence

[bold]History & Memory:[/bold]
  /history    List past conversations
  /restore    Resume a previous session (usage: /restore <id>)
  /memories   Show stored workspace memories
  /remember   Store a memory (usage: /remember <text>)
  /forget     Delete a memory (usage: /forget <id>)

[bold]Operational Capabilities:[/bold]
  • File operations: read, write, edit, append
  • Codebase search: glob patterns, regex content search
  • Command execution: bash shell access
  • Memory: remember context across conversations
  • MCP tools: extended capabilities via [server] prefix

[bold]Pro Tips:[/bold]
  • Be direct. State objectives clearly.
  • I act first, explain after. No hesitation.
  • Ask me to remember project preferences.
  • Use /restore to continue past conversations.

[dim]*CLANK* Systems ready for input. *BZZZT*[/dim]
"""
        self._console.print(help_text)

    def clear(self) -> None:
        """Clear the console."""
        self._console.clear()

    def rule(self, title: str = "") -> None:
        """Print a horizontal rule."""
        self._console.rule(title)

    def get_loading_message(self) -> str:
        """Get a random Clanker-themed loading message."""
        return random.choice(LOADING_MESSAGES)

    @contextmanager
    def loading_spinner(self, message: str | None = None):
        """Show a loading spinner with a Clanker-themed message.

        Args:
            message: Optional custom message. If None, uses a random themed message.

        Yields:
            The Live display object for manual control if needed.
        """
        if message is None:
            message = self.get_loading_message()

        spinner = Spinner("dots", text=Text(f" {message}", style="cyan"))
        with Live(spinner, console=self._console, refresh_per_second=10, transient=True) as live:
            yield live

    def print_token_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        context_used_percent: float,
        cache_read: int = 0,
        cache_creation: int = 0,
    ) -> None:
        """Print token usage and context remaining.

        Args:
            input_tokens: Tokens used for input.
            output_tokens: Tokens generated in response.
            context_used_percent: Percentage of context window used.
            cache_read: Tokens read from cache (Anthropic).
            cache_creation: Tokens used for cache creation (Anthropic).
        """
        remaining = max(0.0, 100.0 - context_used_percent)

        text = Text()
        text.append("  [", style="dim")
        text.append(f"in:{input_tokens:,}", style="dim green")
        text.append(" ", style="dim")
        text.append(f"out:{output_tokens:,}", style="dim yellow")

        # Show cache info if present (Anthropic)
        if cache_read > 0:
            text.append(" ", style="dim")
            text.append(f"cache:{cache_read:,}", style="dim magenta")

        # Context remaining with color coding
        text.append(" | ", style="dim")

        # Color based on remaining context
        if remaining > 50:
            ctx_style = "green"
        elif remaining > 20:
            ctx_style = "yellow"
        else:
            ctx_style = "red"

        text.append(f"{remaining:.0f}%", style=ctx_style)
        text.append(" ctx remaining", style="dim")
        text.append("]", style="dim")

        self._console.print(text)
