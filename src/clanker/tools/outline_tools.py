"""Structural code navigation and symbol outlining tool."""

from __future__ import annotations

import ast
import contextlib
import re
from typing import Any

from langchain_core.tools import tool

from clanker.logging import get_logger
from clanker.utils.sandbox import is_path_safe
from clanker.utils.validators import validate_file_path

logger = get_logger("tools.outline")

MAX_FILE_SIZE = 5_000_000  # 5MB


def _format_py_arg(arg: ast.arg) -> str:
    """Format an ast.arg with optional type annotation."""
    res = arg.arg
    if arg.annotation:
        with contextlib.suppress(Exception):
            res += f": {ast.unparse(arg.annotation)}"
    return res


def _format_py_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Reconstruct function or method signature from AST."""
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    args_parts: list[str] = []

    posonly = getattr(node.args, "posonlyargs", [])
    args = node.args.args
    defaults = node.args.defaults
    kwonly = node.args.kwonlyargs
    kw_defaults = node.args.kw_defaults

    # Match defaults to args from the right
    pos_args = posonly + args
    num_defaults = len(defaults)
    first_default_idx = len(pos_args) - num_defaults

    for i, a in enumerate(pos_args):
        formatted = _format_py_arg(a)
        if i >= first_default_idx:
            def_idx = i - first_default_idx
            try:
                formatted += f" = {ast.unparse(defaults[def_idx])}"
            except Exception:
                formatted += " = ..."
        args_parts.append(formatted)
        if posonly and i == len(posonly) - 1:
            args_parts.append("/")

    if node.args.vararg:
        arg_str = f"*{node.args.vararg.arg}"
        if node.args.vararg.annotation:
            with contextlib.suppress(Exception):
                arg_str += f": {ast.unparse(node.args.vararg.annotation)}"
        args_parts.append(arg_str)
    elif kwonly:
        args_parts.append("*")

    for a, d in zip(kwonly, kw_defaults, strict=False):
        formatted = _format_py_arg(a)
        if d is not None:
            try:
                formatted += f" = {ast.unparse(d)}"
            except Exception:
                formatted += " = ..."
        args_parts.append(formatted)

    if node.args.kwarg:
        arg_str = f"**{node.args.kwarg.arg}"
        if node.args.kwarg.annotation:
            with contextlib.suppress(Exception):
                arg_str += f": {ast.unparse(node.args.kwarg.annotation)}"
        args_parts.append(arg_str)

    sig = f"{prefix}{node.name}({', '.join(args_parts)})"
    if node.returns:
        with contextlib.suppress(Exception):
            sig += f" -> {ast.unparse(node.returns)}"
    return sig


def _outline_python(content: str, max_depth: int) -> tuple[str, list[dict[str, Any]]]:
    """Parse Python source and extract classes, methods, and functions."""
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        logger.debug("Python ast.parse failed: %s; falling back to generic outline", e)
        return _outline_generic(content)

    symbols: list[dict[str, Any]] = []
    lines_out: list[str] = []

    def walk_node(node: ast.AST, depth: int, is_class_member: bool = False) -> None:
        if depth > max_depth:
            return

        for child in getattr(node, "body", []):
            indent = "  " * (depth - 1)
            if isinstance(child, ast.ClassDef):
                bases = []
                for b in child.bases:
                    with contextlib.suppress(Exception):
                        bases.append(ast.unparse(b))
                base_str = f"({', '.join(bases)})" if bases else ""
                start = getattr(child, "lineno", 0)
                end = getattr(child, "end_lineno", start)
                sym: dict[str, Any] = {
                    "name": child.name,
                    "kind": "class",
                    "start_line": start,
                    "end_line": end,
                    "signature": f"class {child.name}{base_str}",
                    "children": [],
                }
                symbols.append(sym)
                line_range = f"Lines {start}-{end}: " if end > start else f"Line {start}: "
                lines_out.append(f"{indent}{line_range}class {child.name}{base_str}")

                doc = ast.get_docstring(child)
                if doc:
                    first_line = doc.strip().split("\n")[0]
                    lines_out.append(f"{indent}  # {first_line}")

                # Traverse methods within class
                if depth < max_depth:
                    for sub in child.body:
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            sub_start = getattr(sub, "lineno", 0)
                            sub_end = getattr(sub, "end_lineno", sub_start)
                            sig = _format_py_signature(sub)
                            is_async = isinstance(sub, ast.AsyncFunctionDef)
                            kind = "async method" if is_async else "method"
                            sub_sym: dict[str, Any] = {
                                "name": sub.name,
                                "kind": kind,
                                "start_line": sub_start,
                                "end_line": sub_end,
                                "signature": sig,
                            }
                            sym["children"].append(sub_sym)
                            sub_range = (
                                f"Lines {sub_start}-{sub_end}: "
                                if sub_end > sub_start
                                else f"Line {sub_start}: "
                            )
                            lines_out.append(f"{indent}  {sub_range}{sig}")

            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = getattr(child, "lineno", 0)
                end = getattr(child, "end_lineno", start)
                sig = _format_py_signature(child)
                is_async = isinstance(child, ast.AsyncFunctionDef)
                kind = (
                    "async method"
                    if is_class_member and is_async
                    else (
                        "method"
                        if is_class_member
                        else ("async function" if is_async else "function")
                    )
                )
                sym = {
                    "name": child.name,
                    "kind": kind,
                    "start_line": start,
                    "end_line": end,
                    "signature": sig,
                    "children": [],
                }
                symbols.append(sym)
                line_range = f"Lines {start}-{end}: " if end > start else f"Line {start}: "
                lines_out.append(f"{indent}{line_range}{sig}")

                doc = ast.get_docstring(child)
                if doc:
                    first_line = doc.strip().split("\n")[0]
                    lines_out.append(f"{indent}  # {first_line}")

                if depth < max_depth:
                    walk_node(child, depth + 1, is_class_member=False)

    walk_node(tree, 1)
    return "\n".join(lines_out) if lines_out else "(no symbols found)", symbols


def _outline_javascript_typescript(
    content: str, max_depth: int
) -> tuple[str, list[dict[str, Any]]]:
    """Extract classes, interfaces, types, and functions from JS/TS."""
    symbols: list[dict[str, Any]] = []
    lines_out: list[str] = []

    pattern = re.compile(
        r"^(?P<indent>[ \t]*)"
        r"(?:export\s+(?:default\s+)?)?"
        r"(?:"
        r"(?:(?:async\s+)?function\s+(?P<func_name>[A-Za-z0-9_$]+)\s*\([^)]*\))|"
        r"(?:(?:const|let|var)\s+(?P<arrow_name>[A-Za-z0-9_$]+)\s*=\s*(?:async\s*)?\([^)]*\)(?:\s*:[^{=]+)?\s*=>)|"
        r"(?:class\s+(?P<class_name>[A-Za-z0-9_$]+)(?:\s+extends\s+[A-Za-z0-9_$.]+)?)|"
        r"(?:interface\s+(?P<interface_name>[A-Za-z0-9_$]+))|"
        r"(?:type\s+(?P<type_name>[A-Za-z0-9_$]+)\s*=)"
        r")",
        re.MULTILINE,
    )

    for i, line in enumerate(content.splitlines(), start=1):
        m = pattern.search(line)
        if not m:
            continue
        indent_len = len(m.group("indent"))
        depth = 1 if indent_len == 0 else min(max_depth, (indent_len // 2) + 1)
        if depth > max_depth:
            continue

        raw = line.strip()
        name = (
            m.group("class_name")
            or m.group("func_name")
            or m.group("arrow_name")
            or m.group("interface_name")
            or m.group("type_name")
            or "unknown"
        )
        kind = "function"
        if m.group("class_name"):
            kind = "class"
        elif m.group("interface_name"):
            kind = "interface"
        elif m.group("type_name"):
            kind = "type"

        symbols.append(
            {
                "name": name,
                "kind": kind,
                "start_line": i,
                "signature": raw,
            }
        )
        indent_str = "  " * (depth - 1)
        lines_out.append(f"{indent_str}Line {i}: {raw}")

    return "\n".join(lines_out) if lines_out else "(no symbols found)", symbols


def _outline_go(content: str, max_depth: int) -> tuple[str, list[dict[str, Any]]]:
    """Extract functions, methods, structs, and interfaces from Go."""
    symbols: list[dict[str, Any]] = []
    lines_out: list[str] = []

    pattern = re.compile(
        r"^(?P<indent>[ \t]*)"
        r"(?:"
        r"(?:func\s+(?:\([^)]+\)\s+)?(?P<func_name>[A-Za-z0-9_]+)\s*\([^)]*\)[^{]*)|"
        r"(?:type\s+(?P<type_name>[A-Za-z0-9_]+)\s+(?P<type_kind>struct|interface))"
        r")",
        re.MULTILINE,
    )

    for i, line in enumerate(content.splitlines(), start=1):
        m = pattern.search(line)
        if not m:
            continue
        raw = line.strip().rstrip("{").strip()
        name = m.group("func_name") or m.group("type_name") or "unknown"
        kind = m.group("type_kind") or ("method" if "(" in line[: line.find(name)] else "function")
        symbols.append(
            {
                "name": name,
                "kind": kind,
                "start_line": i,
                "signature": raw,
            }
        )
        lines_out.append(f"Line {i}: {raw}")

    return "\n".join(lines_out) if lines_out else "(no symbols found)", symbols


def _outline_rust(content: str, max_depth: int) -> tuple[str, list[dict[str, Any]]]:
    """Extract functions, structs, enums, and traits from Rust."""
    symbols: list[dict[str, Any]] = []
    lines_out: list[str] = []

    pattern = re.compile(
        r"^(?P<indent>[ \t]*)"
        r"(?:pub\s+(?:\([^)]+\)\s+)?)?"
        r"(?:"
        r"(?:(?:async\s+)?fn\s+(?P<fn_name>[A-Za-z0-9_]+)\s*(?:<[^>]+>)?\s*\([^)]*\)[^{]*)|"
        r"(?:struct\s+(?P<struct_name>[A-Za-z0-9_]+))|"
        r"(?:enum\s+(?P<enum_name>[A-Za-z0-9_]+))|"
        r"(?:trait\s+(?P<trait_name>[A-Za-z0-9_]+))|"
        r"(?:impl(?:<[^>]+>)?\s+(?P<impl_name>[^{]+))"
        r")",
        re.MULTILINE,
    )

    for i, line in enumerate(content.splitlines(), start=1):
        m = pattern.search(line)
        if not m:
            continue
        raw = line.strip().rstrip("{").strip()
        name = (
            m.group("fn_name")
            or m.group("struct_name")
            or m.group("enum_name")
            or m.group("trait_name")
            or (m.group("impl_name") or "").strip()
            or "unknown"
        )
        kind = "function"
        if m.group("struct_name"):
            kind = "struct"
        elif m.group("enum_name"):
            kind = "enum"
        elif m.group("trait_name"):
            kind = "trait"
        elif m.group("impl_name"):
            kind = "impl"

        symbols.append(
            {
                "name": name,
                "kind": kind,
                "start_line": i,
                "signature": raw,
            }
        )
        lines_out.append(f"Line {i}: {raw}")

    return "\n".join(lines_out) if lines_out else "(no symbols found)", symbols


def _outline_markdown(content: str) -> tuple[str, list[dict[str, Any]]]:
    """Extract Markdown section headings with hierarchy."""
    symbols: list[dict[str, Any]] = []
    lines_out: list[str] = []

    heading_pattern = re.compile(r"^(#{1,6})\s+(.*)$")

    for i, line in enumerate(content.splitlines(), start=1):
        m = heading_pattern.match(line)
        if not m:
            continue
        level = len(m.group(1))
        title = m.group(2).strip()
        indent = "  " * (level - 1)
        symbols.append(
            {
                "name": title,
                "kind": f"h{level}",
                "start_line": i,
                "level": level,
            }
        )
        lines_out.append(f"{indent}Line {i}: {'#' * level} {title}")

    return "\n".join(lines_out) if lines_out else "(no headings found)", symbols


def _outline_generic(content: str) -> tuple[str, list[dict[str, Any]]]:
    """Generic fallback for other file formats."""
    symbols: list[dict[str, Any]] = []
    lines_out: list[str] = []

    pattern = re.compile(
        r"^[ \t]*(?:def|class|function|func|fn|interface|type)\s+([A-Za-z0-9_$]+)",
        re.MULTILINE,
    )

    for i, line in enumerate(content.splitlines(), start=1):
        m = pattern.search(line)
        if m:
            raw = line.strip()
            name = m.group(1)
            symbols.append({"name": name, "kind": "symbol", "start_line": i, "signature": raw})
            lines_out.append(f"Line {i}: {raw}")

    return "\n".join(lines_out) if lines_out else "(no symbols found)", symbols


@tool
def outline_file(file_path: str, max_depth: int = 2) -> dict[str, Any]:
    """Extract a structural symbol outline of a file without reading all its implementation.

    Shows classes, functions, methods, interfaces, type definitions, headings,
    and signatures with their exact line numbers. Ideal for exploring large files
    before deciding which specific lines or functions to read or edit.

    Supported languages include Python (full AST), JavaScript, TypeScript, Go,
    Rust, Markdown, and generic code fallback.

    Args:
        file_path: Path to the file to outline.
        max_depth: Maximum nesting depth for classes/methods (default: 2).

    Returns:
        A dict with `ok`, `path`, `language`, `outline` (formatted string),
        and `total_symbols`.
    """
    try:
        path = validate_file_path(file_path)
    except ValueError as e:
        return {"ok": False, "error": str(e), "path": file_path}

    ok, reason = is_path_safe(str(path))
    if not ok:
        return {"ok": False, "error": reason, "path": file_path}

    if not path.exists():
        return {"ok": False, "error": f"File not found: {file_path}", "path": file_path}

    if not path.is_file():
        return {"ok": False, "error": f"Not a regular file: {file_path}", "path": file_path}

    try:
        size = path.stat().st_size
        if size > MAX_FILE_SIZE:
            return {
                "ok": False,
                "error": f"File exceeds maximum outline size ({size} > {MAX_FILE_SIZE} bytes)",
                "path": file_path,
            }

        raw_bytes = path.read_bytes()
        # Binary check: null bytes usually indicate binary
        if b"\x00" in raw_bytes[:1024]:
            return {"ok": False, "error": "Cannot outline binary file", "path": file_path}

        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            content = raw_bytes.decode("latin-1")
        except Exception as e:
            return {"ok": False, "error": f"Failed to decode file: {e}", "path": file_path}
    except Exception as e:
        return {"ok": False, "error": f"Error reading file: {e}", "path": file_path}

    ext = path.suffix.lower()
    name = path.name.lower()

    if ext == ".py":
        lang = "python"
        outline_str, symbols = _outline_python(content, max_depth)
    elif ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
        lang = "javascript/typescript"
        outline_str, symbols = _outline_javascript_typescript(content, max_depth)
    elif ext == ".go":
        lang = "go"
        outline_str, symbols = _outline_go(content, max_depth)
    elif ext == ".rs":
        lang = "rust"
        outline_str, symbols = _outline_rust(content, max_depth)
    elif ext in (".md", ".markdown", ".rst") or name in ("readme", "license"):
        lang = "markdown"
        outline_str, symbols = _outline_markdown(content)
    else:
        lang = "generic"
        outline_str, symbols = _outline_generic(content)

    return {
        "ok": True,
        "path": file_path,
        "language": lang,
        "total_symbols": len(symbols),
        "outline": outline_str,
    }
