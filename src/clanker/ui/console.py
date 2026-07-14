"""Console output management using Rich."""

import json
import random
from contextlib import contextmanager

from rich.console import Console as RichConsole
from rich.console import Group
from rich.live import Live
from rich import box
from rich.markdown import Heading, Markdown


class _LeftAlignedHeading(Heading):
    """Heading that renders left-aligned instead of Rich's default center."""

    def __rich_console__(self, console, options):  # type: ignore[override]
        text = self.text
        text.justify = "left"
        if self.tag == "h1":
            yield Panel(text, box=box.HEAVY, style="markdown.h1.border")
        else:
            if self.tag == "h2":
                yield Text("")
            yield text


# Replace default heading renderer for our Markdown output.
Markdown.elements["heading_open"] = _LeftAlignedHeading
from rich.markup import escape
from rich.panel import Panel
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.text import Text
from rich.theme import Theme

# Eagerly materialize pygments lexers AND styles at module import time.
# Rich's Markdown/Syntax renderers do lazy string-based lookup
# (`get_lexer_by_name(...)`, `get_style_by_name(...)`) which under
# PyInstaller can fail later with `zlib.error: incorrect header check`
# once subprocesses have been spawned (the bundle archive FD state gets
# corrupted by forks). Touching the registries now guarantees everything
# is in sys.modules before any subprocess runs.
try:
    from pygments.lexers import get_all_lexers, get_lexer_by_name
    from pygments.styles import get_all_styles, get_style_by_name

    _ = list(get_all_lexers())
    for _name in (
        "python", "bash", "shell", "json", "yaml", "toml",
        "javascript", "typescript", "html", "css", "markdown",
        "text", "diff", "sql", "go", "rust", "c", "cpp", "java",
    ):
        try:
            get_lexer_by_name(_name)
        except Exception:  # noqa: BLE001
            pass

    # Force every style module into sys.modules. Rich defaults to
    # "monokai" but users / themes may pick others.
    for _style in list(get_all_styles()):
        try:
            get_style_by_name(_style)
        except Exception:  # noqa: BLE001
            pass
except Exception:  # noqa: BLE001
    # Pygments missing or import failure — Rich will degrade gracefully.
    pass

from clanker.config import get_settings


def _job_label(job_id: str) -> str:
    """Return a friendly label for a job id, falling back to the id itself."""
    jid = str(job_id or "")
    if not jid or jid == "all":
        return jid or "all"
    try:
        from clanker.tools.background import get_job_manager

        job = get_job_manager().get(jid)
        if job and job.name:
            return job.name
    except Exception:  # noqa: BLE001
        pass
    return jid

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
    # Tool badge colors — teal bg pill like the screenshot
    "tool": "bold rgb(0,210,180)",
    "tool.badge": "black on rgb(0,190,220)",
    "tool.arg": "rgb(200,220,210)",
    "tool.result": "rgb(130,220,100)",  # lime-ish green for ✓
    "tool.error": "bold red",  # red ✗ for failed commands
    # Token-usage badge — muted dark mauve-pink pill (a subdued cousin of the
    # assistant-panel hot pink), tying the per-turn usage summary to the
    # response it sits beneath without competing with it for attention.
    "tokens.badge": "rgb(230,195,215) on rgb(80,38,62)",
    "user": "bold rgb(0,210,180)",
    "assistant": "rgb(230,230,230)",
    "prompt.arrow": "bold rgb(0,210,180)",
})


# A borderless box that draws ONLY a left edge -- the "quote bar" look shared by
# the assistant message panel and the notify tool. Reused so both stay in sync.
_LEFT_BORDER_BOX = box.Box(
    "│   \n"
    "│   \n"
    "│   \n"
    "│   \n"
    "│   \n"
    "│   \n"
    "│   \n"
    "│   "
)


class Console:
    """Rich console wrapper for Clanker output."""

    def __init__(self, agent_label: str | None = None):
        """Initialize the console.

        Args:
            agent_label: Optional agent name shown as a prefix on tool rows and
                output lines so the user can tell which agent is acting.
                ``None`` means the main Clanker agent.
        """
        self._console = RichConsole(theme=CLANKER_THEME)
        self._settings = get_settings()
        self._agent_label = agent_label

    def _agent_prefix(self) -> str:
        """Return a styled agent prefix string for display."""
        if self._agent_label:
            return f"[{self._agent_label}] "
        return ""

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
        """Print a user message with a clean arrow prompt matching the screenshot."""
        text = Text()
        text.append("❯ ", style="prompt.arrow")
        text.append(message, style="bold white")
        self._console.print(text)

    def print_assistant_message(self, message: str) -> None:
        """Print an assistant message using Markdown with only a pink left border."""
        message_str = message.strip()
        if not message_str:
            return

        try:
            markdown_content = Markdown(message_str)
            panel = Panel(
                markdown_content,
                box=_LEFT_BORDER_BOX,
                border_style="rgb(255,105,180)",
                padding=(0, 2),
            )
            self._console.print(panel)
        except Exception:  # noqa: BLE001
            self._console.print(
                Panel(
                    message_str,
                    box=_LEFT_BORDER_BOX,
                    border_style="rgb(255,105,180)",
                    padding=(0, 2),
                )
            )

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

    def _tool_summary_arg(self, tool_name: str, args: dict) -> str:
        """Return a short human-readable argument string for a tool call."""
        if tool_name in ("read_file", "write_file", "append_file", "edit_file"):
            return str(args.get("file_path", ""))
        elif tool_name == "execute_shell":
            return self._truncate(str(args.get("command", "")), 60)
        elif tool_name == "bash_background":
            name_val = args.get("name")
            name = str(name_val).strip() if name_val is not None else ""
            cmd = self._truncate(str(args.get("command", "")), 50)
            return f"[{name}] {cmd}" if name else cmd
        elif tool_name in ("bash_status", "bash_output", "bash_wait", "bash_kill"):
            return _job_label(str(args.get("job_id", "all")))
        elif tool_name == "glob_search":
            pat = str(args.get("pattern", "*"))
            path = str(args.get("path", ""))
            return f"{pat} in {path}" if path and path != "." else pat
        elif tool_name == "grep_search":
            pat = self._truncate(str(args.get("pattern", "")), 40)
            path = str(args.get("path", ""))
            return f"{pat} in {path}" if path and path != "." else pat
        elif tool_name == "list_directory":
            return str(args.get("path", "."))
        elif tool_name == "web_search":
            return self._truncate(str(args.get("query", "")), 60)
        elif tool_name == "web_read":
            return self._truncate(str(args.get("url", "")), 70)
        elif tool_name == "load_skill":
            return str(args.get("name", ""))
        elif tool_name in ("remember", "recall"):
            return self._truncate(str(args.get("topic", "") or args.get("query", "")), 40)
        elif tool_name == "notify":
            return self._truncate(str(args.get("message", "")), 40)
        else:
            # MCP tools or unknown
            if "__" in tool_name:
                return args.get("query", args.get("path", args.get("input", "")))
            for key in ["query", "path", "url", "input", "text", "command", "name"]:
                if key in args:
                    return self._truncate(str(args[key]), 40)
            if args:
                return self._truncate(str(list(args.values())[0]), 40)
            return ""

    def _print_tool_row(
        self,
        tool_name: str,
        arg_str: str,
        result_summary: str | None = None,
    ) -> None:
        """Print a single tool row in screenshot style:

           [tool_name]  arg_str                    ✓ result_summary
        """
        # Resolve display name for MCP tools (server__tool -> strip prefix for label)
        display_name = tool_name
        mcp_prefix = ""
        if "__" in tool_name:
            parts = tool_name.split("__", 1)
            mcp_prefix = f"[{parts[0]}] "
            display_name = parts[1]

        text = Text()
        # Teal badge: [ tool_name ]
        text.append(" ", style="dim")
        agent_prefix = self._agent_prefix()
        if agent_prefix:
            text.append(agent_prefix, style="dim cyan")
        text.append(f" {display_name} ", style="tool.badge")
        text.append(" ", style="dim")
        if mcp_prefix:
            text.append(mcp_prefix, style="dim cyan")
        # Argument in muted colour
        if arg_str:
            text.append(arg_str, style="tool.arg")
        # Right-aligned result on same line
        if result_summary:
            text.append("  ", style="dim")
            text.append("✓ ", style="bold tool.result")
            text.append(result_summary, style="tool.result")
        self._console.print(text)

    def print_tool_use(self, tool_name: str, args: dict | None = None) -> None:
        """Print a concise, user-friendly tool usage message."""
        if not self._settings.output.show_tool_calls:
            return

        args = args or {}
        arg_str = self._tool_summary_arg(tool_name, args)
        self._print_tool_row(tool_name, arg_str)

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
        """Print dim/muted text with consistent indent on all lines."""
        indent = "    "
        agent_prefix = self._agent_prefix()
        # Replace tabs with spaces for consistent alignment
        text_str = text_str.replace("\t", "  ")
        lines = text_str.split("\n")
        for line in lines:
            text = Text()
            text.append(indent, style="dim")
            if agent_prefix:
                text.append(agent_prefix, style="dim cyan")
            text.append(line, style="dim")
            self._console.print(text)

    def _compact_result_summary(
        self,
        result: str,
        tool_name: str,
        tool_input: dict | None,
        max_chars: int = 60,
    ) -> str | None:
        """Return a short one-line summary string for a tool result, or None to suppress."""
        result = result.strip()
        if not result:
            return None

        parsed = self._parse_tool_json(result)

        if tool_name in ("write_file", "append_file"):
            # Diff is shown inline; just confirm with line count if available
            if parsed and parsed.get("ok"):
                lines_written = parsed.get("lines_written") or parsed.get("lines")
                if lines_written:
                    return f"wrote {lines_written} lines"
                return "saved"
            return None

        if tool_name == "edit_file":
            if parsed and parsed.get("ok"):
                path = parsed.get("path") or (tool_input or {}).get("file_path", "")
                if path and tool_input:
                    new_str = tool_input.get("new_string", "")
                    # Try to find the line number of new_str in the file
                    try:
                        from pathlib import Path
                        full_path = Path(path)
                        if full_path.exists():
                            content = full_path.read_text(encoding="utf-8", errors="ignore")
                            idx = content.find(new_str)
                            if idx != -1:
                                line_num = content[:idx].count("\n") + 1
                                return f"patched at line {line_num}"
                    except Exception:
                        pass
                return "saved"
            if parsed and not parsed.get("ok"):
                return str(parsed.get("error", "error"))[:max_chars]
            return None

        if parsed and parsed.get("ok") and "message" in parsed and "memory_id" in parsed:
            return str(parsed.get("message", ""))[:max_chars]

        if tool_name == "read_file":
            if parsed and parsed.get("ok"):
                content = parsed.get("content", "")
                lines = content.splitlines() if content else []
                path = parsed.get("path", "") or (tool_input or {}).get("file_path", "")
                short = self._shorten_path(path) if path else ""
                return f"read {len(lines)} lines{f'  {short}' if short else ''}"
            if parsed and not parsed.get("ok"):
                return str(parsed.get("message", "error"))[:max_chars]
            return None

        if tool_name == "read_project_instructions":
            if parsed and parsed.get("ok"):
                if parsed.get("found"):
                    content = parsed.get("content", "")
                    lines = content.splitlines() if content else []
                    return f"read AGENTS.md  {len(lines)} lines"
                return "no AGENTS.md found"
            return None

        if tool_name == "load_skill":
            if parsed and parsed.get("ok"):
                name = parsed.get("name", "?")
                return f"loaded {name}"
            if parsed and not parsed.get("ok"):
                return str(parsed.get("error", "not found"))[:max_chars]
            return None

        if tool_name == "load_agent":
            if parsed and parsed.get("ok"):
                name = parsed.get("name", "?")
                desc = parsed.get("description", "")
                summary = f"loaded {name}"
                if desc:
                    summary += f"  — {desc[:max_chars - len(summary) - 3]}"
                return summary[:max_chars]
            if parsed and not parsed.get("ok"):
                return str(parsed.get("error", "not found"))[:max_chars]
            return None

        if tool_name in ("bash", "execute_shell"):
            # Failure: result starts with "Command exited with code N\n{output}".
            # Summarize as the exit-code line so the red ✗ has a clear message.
            if result.startswith("Command exited with code"):
                first_line = result.splitlines()[0] if result.splitlines() else result
                extra = len(result.splitlines()) - 1
                suffix = f"  (+{extra} lines)" if extra > 0 else ""
                return self._truncate(first_line, max_chars) + suffix
            raw = (parsed.get("output") or parsed.get("stdout") or parsed.get("stderr") or result) if parsed else result
            raw = raw.strip()
            if not raw:
                return "done"
            first_line = raw.splitlines()[0]
            total_lines = len(raw.splitlines())
            suffix = f"  (+{total_lines - 1} lines)" if total_lines > 1 else ""
            return self._truncate(first_line, max_chars) + suffix

        if tool_name == "execute_shell":
            lines = result.splitlines()
            first = lines[0] if lines else "done"
            suffix = f"  (+{len(lines) - 1} lines)" if len(lines) > 1 else ""
            return self._truncate(first, max_chars) + suffix

        if tool_name == "glob_search":
            lines = [line.strip() for line in result.splitlines() if line.strip()]
            if not lines:
                return None
            first = lines[0]
            if first.startswith("Found "):
                parts = first.split()
                if len(parts) >= 2:
                    return f"{parts[1]} file{'s' if parts[1] != '1' else ''}"
            return first

        if tool_name == "grep_search":
            lines = [line.strip() for line in result.splitlines() if line.strip()]
            if not lines:
                return None
            first = lines[0]
            if first.startswith("Found "):
                parts = first.split()
                if len(parts) >= 2:
                    matches_str = f"{parts[1]} {parts[2]}"  # "3 matches"
                    if len(lines) > 1:
                        match_line = lines[1]
                        match_parts = match_line.split(":", 2)
                        if len(match_parts) >= 2:
                            file_path = match_parts[0]
                            return f"{matches_str} in {file_path}"
                    return matches_str
            return first

        if tool_name == "list_directory":
            if parsed and parsed.get("ok"):
                items = parsed.get("items", [])
                return f"{len(items)} item{'s' if len(items) != 1 else ''}"
            return None

        if tool_name == "remember":
            if parsed and parsed.get("ok"):
                return parsed.get("message", "saved")[:max_chars]
            return None

        if tool_name == "recall":
            if parsed and parsed.get("ok"):
                memories = parsed.get("memories", [])
                n = len(memories)
                return f"{n} memor{'ies' if n != 1 else 'y'} found"
            return None

        if tool_name == "forget":
            if parsed and parsed.get("ok"):
                return parsed.get("message", "deleted")[:max_chars]
            return None

        if tool_name == "list_memories":
            if parsed and parsed.get("ok"):
                total = parsed.get("total", 0) or len(parsed.get("memories", []))
                return f"{total} memor{'ies' if total != 1 else 'y'}"
            return None

        # Fallback: first line of plain result
        lines = result.split("\n")
        first = lines[0].strip()
        total = len(lines)
        suffix = f"  (+{total - 1} lines)" if total > 1 else ""
        if first:
            return self._truncate(first, max_chars) + suffix
        return None

    def _is_failed_tool_result(self, result: str, tool_name: str, tool_input: dict | None) -> bool:
        """Return True if a tool result represents a failure (render ✗ not ✓).

        Shell tools return a plain string that starts with "Command exited with
        code N" on nonzero exit. JSON-returning tools signal failure via
        ``ok: false``.
        """
        result = result.strip()
        if not result:
            return False
        if tool_name in ("bash", "execute_shell") and result.startswith("Command exited with code"):
            return True
        parsed = self._parse_tool_json(result)
        if parsed is not None and parsed.get("ok") is False:
            return True
        return False

    def _print_result_line(self, summary: str, failed: bool = False) -> None:
        """Print a ✓/✗ result summary line matching the screenshot style."""
        text = Text()
        text.append("   ", style="dim")
        if failed:
            text.append("✗ ", style="bold tool.error")
            text.append(summary, style="tool.error")
        else:
            text.append("✓ ", style="bold tool.result")
            text.append(summary, style="tool.result")
        self._console.print(text)

    def print_tool_result(
        self,
        result: str,
        tool_name: str = "",
        tool_input: dict | None = None,
        max_lines: int = 4,
        max_chars: int = 300,
    ) -> None:
        """Print a compact ✓ summary of a tool result in screenshot style."""
        if not self._settings.output.show_tool_calls:
            return

        result = result.strip()
        if not result:
            return

        # Support mock consoles in unit tests
        compact_summary_fn = getattr(self, "_compact_result_summary", None)
        print_result_line_fn = getattr(self, "_print_result_line", None)
        if compact_summary_fn and print_result_line_fn:
            summary = compact_summary_fn(result, tool_name, tool_input, max_chars=60)
            if summary:
                failed = self._is_failed_tool_result(result, tool_name, tool_input)
                print_result_line_fn(summary, failed=failed)
            return

        # Fallback implementation for unit tests
        parsed = self._parse_tool_json(result)
        if parsed and parsed.get("ok") and "message" in parsed and "memory_id" in parsed:
            self._print_dim(str(parsed.get("message", ""))[:max_chars])
            return

        if tool_name == "load_skill":
            if parsed and parsed.get("ok"):
                name = parsed.get("name", "")
                skill_dir = parsed.get("skill_directory", "")
                msg = f"Loaded skill {name}  ({skill_dir})"
                self._print_dim(msg)
            elif parsed and not parsed.get("ok"):
                available = parsed.get("available", [])
                msg = str(parsed.get("error", "Skill not found"))
                if available:
                    msg += f" Available: {', '.join(available)}"
                self._print_dim(msg[:max_chars])
            return

        if tool_name == "load_agent":
            if parsed and parsed.get("ok"):
                name = parsed.get("name", "")
                desc = parsed.get("description", "")
                tools = parsed.get("tools", "")
                if isinstance(tools, list):
                    tools_str = ", ".join(tools) if tools else "(all default tools)"
                else:
                    tools_str = str(tools)
                msg = f"Loaded agent {name}"
                if desc:
                    msg += f"  — {desc[:50]}"
                if tools_str and tools_str != "(all default tools)":
                    msg += f"  [tools: {tools_str}]"
                self._print_dim(msg)
            elif parsed and not parsed.get("ok"):
                available = parsed.get("available", [])
                msg = str(parsed.get("error", "Agent not found"))
                if available:
                    msg += f" Available: {', '.join(available)}"
                self._print_dim(msg[:max_chars])
            return

        lines = result.split('\n')
        display = '\n'.join(lines[:max_lines]) if len(lines) > max_lines else result
        if len(display) > max_chars:
            display = display[:max_chars] + "…"
        self._print_dim(display)



    def print_edit_diff(self, old_string: str, new_string: str) -> None:
        """Print a compact diff showing only the changed lines (with context)."""
        if not self._settings.output.show_tool_calls:
            return

        import difflib

        old_lines = old_string.splitlines() or [""]
        new_lines = new_string.splitlines() or [""]

        # Unified diff with small context window so unchanged shared prefix/suffix
        # (common when old_string/new_string overlap heavily) is collapsed.
        context = 2
        max_lines = 20
        max_line_len = 120

        diff_iter = difflib.unified_diff(old_lines, new_lines, n=context, lineterm="")
        # Skip the file header lines (---, +++) that unified_diff emits.
        rendered: list[Text] = []
        for raw in diff_iter:
            if raw.startswith("---") or raw.startswith("+++"):
                continue
            if raw.startswith("@@"):
                t = Text()
                t.append("    " + raw, style="dim cyan")
                rendered.append(t)
                continue
            sign = raw[:1]
            body = raw[1:]
            if len(body) > max_line_len:
                body = body[:max_line_len] + "..."
            if sign == "+":
                style = "green"
                prefix = "    + "
            elif sign == "-":
                style = "red"
                prefix = "    - "
            else:
                style = "dim"
                prefix = "      "
            t = Text()
            t.append(prefix, style=style)
            t.append(escape(body), style=style)
            rendered.append(t)

        if not rendered:
            # Identical strings (shouldn't normally happen for edits) — show a note.
            self._console.print(Text("    (no textual changes)", style="dim"))
            return

        for line in rendered[:max_lines]:
            self._console.print(line)
        if len(rendered) > max_lines:
            self._console.print(
                Text(f"    ... (+{len(rendered) - max_lines} more diff lines)", style="dim")
            )

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

    def print_notify(self, message: str, level: str = "info", title: str | None = None) -> None:
        """Print an agent status notification (from the notify tool).

        Rendered as fancy bordered Markdown -- the same left-"quote bar" look as
        the assistant's final message, tinted per severity. The colored border
        alone always conveys severity; `title`, when the agent provides one, is
        shown as a bold header above the message. When no title is given, the
        header is omitted entirely -- just the tinted border and the message.

        Args:
            message: The status message sent by the agent.
            level: Severity / display style - "info", "success", "warning", "error".
            title: Optional short heading shown above the message. Omitted
                   (no header line at all) when not provided.
        """
        message_str = (message or "").strip()
        if not message_str:
            return

        # border/tint color per level -- always shown, this is the primary
        # severity cue regardless of whether a title is present.
        level_colors = {
            "info": "rgb(0,190,220)",
            "success": "rgb(130,220,100)",
            "warning": "rgb(240,200,60)",
            "error": "rgb(255,90,90)",
        }
        color = level_colors.get(level, level_colors["info"])

        title_str = (title or "").strip()

        try:
            body = Markdown(message_str)
        except Exception:  # noqa: BLE001
            body = Text(message_str)

        renderable = body
        if title_str:
            # An agent-given heading sits above the message; omitted entirely
            # (no blank header line) when the agent didn't send one.
            header = Text(title_str, style=f"bold {color}")
            renderable = Group(header, body)

        try:
            panel = Panel(
                renderable,
                box=_LEFT_BORDER_BOX,
                border_style=color,
                padding=(0, 2),
            )
            self._console.print(panel)
        except Exception:  # noqa: BLE001
            # Absolute fallback: never let a display error break the agent.
            prefix = f"{title_str}: " if title_str else ""
            self._console.print(Text(f"  {prefix}{message_str}", style=color))

    def print_success(self, message: str) -> None:
        """Print a success message."""
        self._console.print(Text(message, style="success"))

    def print_panel(self, content: str, title: str = "", style: str = "blue") -> None:
        """Print content in a panel."""
        panel = Panel(content, title=title, border_style=style)
        self._console.print(panel)

    def print_welcome(self, user_instructions_loaded: bool = False) -> None:
        """Print welcome message.

        Args:
            user_instructions_loaded: Whether user instructions were loaded from .clanker/instructions.md.
        """
        from clanker.config import get_default_model
        from clanker.runtime import is_yolo_mode

        agent_name = self._settings.agent.name

        # Get current model info
        current_model = get_default_model()
        if current_model:
            model_info = f"{current_model.name} [dim]({current_model.provider})[/dim]"
        else:
            model_info = "[dim]No model configured[/dim]"
        mode_line = ""

        # Yolo mode indicator
        yolo_line = ""
        if is_yolo_mode():
            yolo_line = "\n  [bold yellow]YOLO MODE[/bold yellow] [dim]- bash commands auto-approved[/dim]"

        # User instructions indicator
        instructions_line = ""
        if user_instructions_loaded:
            instructions_line = "\n  [bold magenta]USER INSTRUCTIONS[/bold magenta] [dim]- custom instructions loaded[/dim]"

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
  Model: [bold cyan]{model_info}[/bold cyan]{mode_line}{yolo_line}{instructions_line}
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
  /copilot-login  Connect a GitHub Copilot subscription as a model provider
  /config     Display configuration parameters
  /mcp        Show MCP server connections
  /logs       Access diagnostic log files
  /exit       Initiate shutdown sequence

[bold]History & Memory:[/bold]
  /history    List past conversations
  /restore    Resume a previous session (usage: /restore <id>)
  /compact    Compact the current conversation history manually
  /memories   Show stored workspace memories
  /remember   Store a memory (usage: /remember <text>)
  /forget     Delete a memory (usage: /forget <id>)

[bold]Workflows:[/bold]
  /workflow    List or run a stored workflow (usage: /workflow <name>)

[bold]Skills:[/bold]
  /skill       List or load a skill (usage: /skill <name>); the agent also loads skills automatically

[bold]Operational Capabilities:[/bold]
  • File operations: read, write, edit, append
  • Codebase search: glob patterns, regex content search
  • Command execution: bash shell access
  • Memory: remember context across conversations
  • Skills: model-discovered capabilities from .clanker/skills/
  • MCP tools: extended capabilities via [server] prefix

[bold]Pro Tips:[/bold]
  • Be direct. State objectives clearly.
  • I act first, explain after. No hesitation.
  • Ask me to remember project preferences.
  • Use /restore to continue past conversations.
"""

        help_text += "\n[dim]*CLANK* Systems ready for input. *BZZZT*[/dim]\n"
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
        context_used_percent: float | None,
        cache_read: int = 0,
        cache_creation: int = 0,
        cost_usd: float | None = None,
        session_cost_usd: float | None = None,
    ) -> None:
        """Print token usage and context remaining.

        Args:
            input_tokens: Tokens used for input.
            output_tokens: Tokens generated in response.
            context_used_percent: Percentage of context window used, or None when
                the model config does not specify max_input_tokens. When None,
                the context segment is omitted entirely (no misleading number).
            cache_read: Tokens read from cache (Anthropic).
            cache_creation: Tokens used for cache creation (Anthropic).
            cost_usd: USD cost for this turn, or None when pricing is not configured.
            session_cost_usd: Cumulative USD cost for the session, or None.
        """
        text = Text()
        text.append("  ", style="dim")
        # Muted pill badge, echoing the tool-name badge but subdued so the usage
        # summary reads as a quiet footnote to the response above it.
        text.append(" tokens ", style="tokens.badge")
        text.append(" ", style="dim")
        text.append(f"in:{input_tokens:,}", style="dim green")
        text.append(" ", style="dim")
        text.append(f"out:{output_tokens:,}", style="dim yellow")

        # Show cache info if present (Anthropic)
        if cache_read > 0:
            text.append(" ", style="dim")
            text.append(f"cache:{cache_read:,}", style="dim magenta")

        # Show cost for this turn (only when pricing is configured)
        if cost_usd is not None:
            text.append(" ", style="dim")
            # Format smartly: show more decimals for tiny amounts
            if cost_usd < 0.0001:
                cost_str = f"${cost_usd:.6f}"
            elif cost_usd < 0.01:
                cost_str = f"${cost_usd:.4f}"
            else:
                cost_str = f"${cost_usd:.4f}"
            text.append(cost_str, style="dim cyan")
            # Show session total if we have more than one turn
            if session_cost_usd is not None and session_cost_usd != cost_usd:
                if session_cost_usd < 0.0001:
                    sess_str = f"${session_cost_usd:.6f}"
                elif session_cost_usd < 0.01:
                    sess_str = f"${session_cost_usd:.4f}"
                else:
                    sess_str = f"${session_cost_usd:.4f}"
                text.append(f" (session {sess_str})", style="dim")

        # Context remaining — only when the window is known. Without a configured
        # max_input_tokens we cannot compute a percentage, so we show nothing
        # rather than a fabricated value. Rendered as a right-aligned depleting
        # progress bar (fuel gauge): the filled portion is context REMAINING.
        if context_used_percent is not None:
            remaining = max(0.0, 100.0 - context_used_percent)

            # Color based on remaining context
            if remaining > 50:
                ctx_style = "green"
            elif remaining > 20:
                ctx_style = "yellow"
            else:
                ctx_style = "red"

            bar_width = 16
            filled = int(round(remaining / 100.0 * bar_width))
            filled = max(0, min(bar_width, filled))

            gauge = Text()
            gauge.append(f"{remaining:.0f}% ", style=ctx_style)
            gauge.append("█" * filled, style=ctx_style)
            gauge.append("░" * (bar_width - filled), style="dim")

            # Right-align the gauge: pad between the left summary and the bar so
            # it sits flush to the console's right edge (min one space).
            pad = self.width - text.cell_len - gauge.cell_len
            text.append(" " * max(1, pad))
            text.append_text(gauge)

        self._console.print(text)

