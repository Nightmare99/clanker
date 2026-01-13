"""Console output management using Rich."""

from rich.console import Console as RichConsole
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
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

    def print_markdown(self, text: str) -> None:
        """Print markdown-formatted text."""
        md = Markdown(text)
        self._console.print(md)

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
        """Print an assistant message."""
        self.print_markdown(message)

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
            path = self._shorten_path(args.get("file_path", "file"))
            text.append(f"Read {path}", style="tool")

        elif tool_name == "write_file":
            path = self._shorten_path(args.get("file_path", "file"))
            text.append(f"Write {path}", style="tool")

        elif tool_name == "edit_file":
            path = self._shorten_path(args.get("file_path", "file"))
            text.append(f"Edit {path}", style="tool")

        elif tool_name == "bash":
            cmd = self._truncate(args.get("command", ""), 60)
            text.append(f"Run: {cmd}", style="tool")

        elif tool_name == "glob_search":
            pattern = args.get("pattern", "*")
            path = args.get("path", ".")
            text.append(f"Find: {pattern}", style="tool")
            if path != ".":
                text.append(f" in {self._shorten_path(path)}", style="dim")

        elif tool_name == "grep_search":
            pattern = self._truncate(args.get("pattern", ""), 30)
            text.append(f"Search: {pattern}", style="tool")

        elif tool_name == "list_directory":
            path = self._shorten_path(args.get("path", "."))
            text.append(f"List: {path}", style="tool")

        else:
            # Generic fallback - show tool name and first arg value
            text.append(tool_name, style="tool")
            if args:
                first_val = str(list(args.values())[0])
                text.append(f": {self._truncate(first_val, 40)}", style="dim")

        self._console.print(text)

    def print_tool_result(self, result: str, truncate: int = 500) -> None:
        """Print a tool result."""
        if not self._settings.output.show_tool_calls:
            return

        display = result[:truncate] + "..." if len(result) > truncate else result
        self._console.print(Text(display, style="dim"))

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
[bold cyan]Clanker[/bold cyan] - AI-Powered Coding Assistant

Type your message to start. Commands:
  [dim]/help[/dim]    - Show help
  [dim]/clear[/dim]   - Clear history
  [dim]/exit[/dim]    - Exit

"""
        self._console.print(welcome)

    def print_help(self) -> None:
        """Print help information."""
        help_text = """
[bold]Available Commands:[/bold]

  /help     Show this help message
  /clear    Clear conversation history
  /model    Show or change the current model
  /exit     Exit Clanker

[bold]Tips:[/bold]

  - Ask me to read, write, or edit files
  - Request code explanations or reviews
  - Ask me to run shell commands
  - Use glob patterns to find files
  - Search code with regex patterns
"""
        self._console.print(help_text)

    def clear(self) -> None:
        """Clear the console."""
        self._console.clear()

    def rule(self, title: str = "") -> None:
        """Print a horizontal rule."""
        self._console.rule(title)
