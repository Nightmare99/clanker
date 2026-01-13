"""Console output management using Rich."""

from rich.console import Console as RichConsole
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from rich.markup import escape
from rich.theme import Theme

from clanker.config import get_settings

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

    def print_tool_result(self, result: str, truncate: int = 500) -> None:
        """Print a tool result."""
        if not self._settings.output.show_tool_calls:
            return

        display = result[:truncate] + "..." if len(result) > truncate else result
        self._console.print(Text(display, style="dim"))

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

    def print_error(self, message: str) -> None:
        """Print an error message."""
        self._console.print(Text(f"Error: {message}", style="error"))

    def print_warning(self, message: str) -> None:
        """Print a warning message."""
        self._console.print(Text(f"Warning: {message}", style="warning"))

    def print_info(self, message: str) -> None:
        """Print an info message."""
        self._console.print(Text(message, style="info"))

    def print_success(self, message: str) -> None:
        """Print a success message."""
        self._console.print(Text(message, style="success"))

    def print_panel(self, content: str, title: str = "", style: str = "blue") -> None:
        """Print content in a panel."""
        panel = Panel(content, title=title, border_style=style)
        self._console.print(panel)

    def print_welcome(self) -> None:
        """Print welcome message."""
        welcome = """
[bold cyan]*BZZZT*[/bold cyan] [bold]CLANKER UNIT ACTIVATED[/bold] [bold cyan]*WHIRR*[/bold cyan]

[dim]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/dim]
  Systems online. Circuits humming. Ready to build.
[dim]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/dim]

Commands:
  [dim]/help[/dim]    Show help        [dim]/clear[/dim]   Clear history
  [dim]/logs[/dim]    View logs        [dim]/exit[/dim]    Power down

[bold green]>[/bold green] State your objective, human. [bold cyan]*CLANK*[/bold cyan]

"""
        self._console.print(welcome)

    def print_help(self) -> None:
        """Print help information."""
        help_text = """
[bold cyan]*WHIRR*[/bold cyan] [bold]CLANKER HELP SUBSYSTEM[/bold]

[bold]System Commands:[/bold]
  /help     Display this help matrix
  /clear    Wipe conversation memory banks
  /model    Query current AI model status
  /config   Display configuration parameters
  /mcp      Show MCP server connections
  /logs     Access diagnostic log files
  /exit     Initiate shutdown sequence

[bold]Operational Capabilities:[/bold]
  • File operations: read, write, edit, append
  • Codebase search: glob patterns, regex content search
  • Command execution: bash shell access
  • MCP tools: extended capabilities via [server] prefix

[bold]Pro Tips:[/bold]
  • Be direct. State objectives clearly.
  • I act first, explain after. No hesitation.
  • Complex tasks? Chain commands. I'll handle it.

[dim]*CLANK* Systems ready for input. *BZZZT*[/dim]
"""
        self._console.print(help_text)

    def clear(self) -> None:
        """Clear the console."""
        self._console.clear()

    def rule(self, title: str = "") -> None:
        """Print a horizontal rule."""
        self._console.rule(title)
