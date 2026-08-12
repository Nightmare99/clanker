"""Shared tool-result summarization for both the CLI console and the TUI chat log.

Single source of truth so the two renderers can't drift out of sync -- the
chat log used to have its own much simpler JSON formatter that only knew about
a "message"/"content"/"path" convention, so anything else (e.g. load_skill's
``{"ok": true, "name": ..., "instructions": ...}``) fell through to a raw JSON
dump. Both renderers now call into this module for the same compact, per-tool
one-line summary.
"""

from __future__ import annotations

import difflib
import json

from rich.markup import escape
from rich.text import Text


def parse_tool_json(result: str) -> dict | None:
    """Try to parse a tool result as JSON. Returns None if not a JSON object."""
    try:
        parsed = json.loads(result)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def shorten_path(path: str, max_parts: int = 3) -> str:
    """Shorten a file path to show last N components."""
    parts = path.rstrip("/").split("/")
    if len(parts) <= max_parts:
        return path
    return ".../" + "/".join(parts[-max_parts:])


def truncate(text: str, max_len: int = 50) -> str:
    """Truncate text with ellipsis if too long."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def compact_result_summary(
    result: str,
    tool_name: str,
    tool_input: dict | None,
    max_chars: int = 60,
) -> str | None:
    """Return a short one-line summary string for a tool result, or None to suppress."""
    result = result.strip()
    if not result:
        return None

    parsed = parse_tool_json(result)

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
            short = shorten_path(path) if path else ""
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
            return truncate(first_line, max_chars) + suffix
        raw = (parsed.get("output") or parsed.get("stdout") or parsed.get("stderr") or result) if parsed else result
        raw = raw.strip()
        if not raw:
            return "done"
        first_line = raw.splitlines()[0]
        total_lines = len(raw.splitlines())
        suffix = f"  (+{total_lines - 1} lines)" if total_lines > 1 else ""
        return truncate(first_line, max_chars) + suffix

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

    if tool_name in ("todo_write", "todo_read"):
        # Full checklist is rendered separately (see build_todo_checklist_text);
        # this one-liner is only the fallback for renderers that don't call it.
        if parsed and parsed.get("ok"):
            summary = parsed.get("summary", {})
            total = summary.get("total", 0)
            completed = summary.get("completed", 0)
            if total == 0:
                return "no todos yet"
            return f"{completed}/{total} done"
        if parsed and not parsed.get("ok"):
            return str(parsed.get("error", "error"))[:max_chars]
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
        return truncate(first, max_chars) + suffix
    return None


def is_failed_tool_result(result: str, tool_name: str, tool_input: dict | None) -> bool:
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
    parsed = parse_tool_json(result)
    return bool(parsed is not None and parsed.get("ok") is False)


_TODO_STATUS_ICONS = {
    "completed": ("✓", "green"),
    "in_progress": ("▶", "bold cyan"),
    "pending": ("☐", "dim"),
}


def build_todo_checklist_text(
    todos: list[dict], indent: str = "  ", max_items: int | None = None
) -> Text | None:
    """Build a checklist card (Rich Text) from a todo_write/todo_read result.

    Shared by the CLI console and the TUI's pinned todo panel so the agent's
    plan renders as an actual checklist -- one line per item with a status
    icon and the active item called out -- instead of a one-line count
    summary. Returns None for an empty list (nothing to show yet).

    ``max_items`` caps how many item lines are shown (with a "+N more" line
    for the rest) -- for the pinned panel, which has bounded screen space;
    pass None (default) to always show every item, as the console does.
    """
    if not todos:
        return None

    total = len(todos)
    completed = sum(1 for t in todos if t.get("status") == "completed")

    result = Text()
    result.append(f"{indent}Plan  ", style="bold")
    result.append(f"{completed}/{total} done", style="bold green" if completed == total else "bold cyan")

    shown = todos if max_items is None else todos[:max_items]
    for item in shown:
        status = item.get("status", "pending")
        icon, icon_style = _TODO_STATUS_ICONS.get(status, _TODO_STATUS_ICONS["pending"])
        if status == "in_progress":
            label = item.get("active_form") or item.get("content", "")
            text_style = "bold"
        elif status == "completed":
            label = item.get("content", "")
            text_style = "dim strike"
        else:
            label = item.get("content", "")
            text_style = "dim"

        result.append("\n")
        result.append(f"{indent}{icon} ", style=icon_style)
        result.append(label, style=text_style)

    overflow = total - len(shown)
    if overflow > 0:
        result.append(f"\n{indent}… +{overflow} more", style="dim")

    return result


def build_edit_diff_text(
    old_string: str,
    new_string: str,
    max_lines: int = 20,
    max_line_len: int = 120,
) -> Text | None:
    """Build a compact unified diff (changed lines + small context) as Rich Text.

    Shared by the CLI console (``Console.print_edit_diff``) and the TUI chat
    log so ``edit_file`` shows the actual lines changed instead of a generic
    "patched at line N" summary. Returns ``None`` if the strings are
    identical (shouldn't normally happen for a real edit).
    """
    old_lines = old_string.splitlines() or [""]
    new_lines = new_string.splitlines() or [""]

    # Small context window so unchanged shared prefix/suffix (common when
    # old_string/new_string overlap heavily) is collapsed rather than shown
    # in full.
    context = 2
    diff_iter = difflib.unified_diff(old_lines, new_lines, n=context, lineterm="")

    rendered: list[Text] = []
    for raw in diff_iter:
        if raw.startswith("---") or raw.startswith("+++"):
            continue
        if raw.startswith("@@"):
            t = Text()
            t.append(raw, style="dim cyan")
            rendered.append(t)
            continue
        sign = raw[:1]
        body = raw[1:]
        if len(body) > max_line_len:
            body = body[:max_line_len] + "..."
        if sign == "+":
            style, prefix = "green", "+ "
        elif sign == "-":
            style, prefix = "red", "- "
        else:
            style, prefix = "dim", "  "
        t = Text()
        t.append(prefix, style=style)
        t.append(escape(body), style=style)
        rendered.append(t)

    if not rendered:
        return None

    shown = rendered[:max_lines]
    overflow = len(rendered) - len(shown)

    result = Text()
    for i, line in enumerate(shown):
        if i > 0:
            result.append("\n")
        result.append_text(line)
    if overflow > 0:
        result.append(f"\n... (+{overflow} more diff lines)", style="dim")

    return result
