"""
Lightweight Markdown → Rich markup adapter with code block extraction.

This is NOT a full Markdown parser.
It supports a safe subset and allows routing fenced code blocks
outside of streaming text rendering.
"""

from __future__ import annotations

import re
from typing import List, Tuple

# ```lang\ncode``` (lang optional)
CODE_FENCE_RE = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)

BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
ITALIC_RE = re.compile(r"\*(.+?)\*")
INLINE_CODE_RE = re.compile(r"`([^`]+)`")
H3_RE = re.compile(r"^###\s+(.*)", re.MULTILINE)
H2_RE = re.compile(r"^##\s+(.*)", re.MULTILINE)
LIST_RE = re.compile(r"^\s*[-*]\s+(.*)", re.MULTILINE)


def extract_code_blocks(text: str) -> Tuple[str, List[tuple[str, str]]]:
    """
    Extract fenced code blocks from text.

    Returns:
        cleaned_text: text with code blocks removed
        code_blocks: list of (language, code)
    """
    code_blocks: List[tuple[str, str]] = []

    def _repl(match: re.Match) -> str:
        lang = match.group(1) or "text"
        code = match.group(2).rstrip()
        code_blocks.append((lang, code))
        return ""  # remove from text

    cleaned = CODE_FENCE_RE.sub(_repl, text)
    return cleaned, code_blocks


def markdown_to_rich(text: str) -> str:
    """Convert a small Markdown subset to Rich markup (no code blocks)."""

    text = H3_RE.sub(r"[bold cyan]\1[/bold cyan]", text)
    text = H2_RE.sub(r"[bold]\1[/bold]", text)

    text = BOLD_RE.sub(r"[bold]\1[/bold]", text)
    text = ITALIC_RE.sub(r"[italic]\1[/italic]", text)
    text = INLINE_CODE_RE.sub(r"[code]\1[/code]", text)

    text = LIST_RE.sub(r"• \1", text)
    return text
