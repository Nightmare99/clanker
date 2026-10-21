"""Separate marked model reasoning from assistant text without guessing from prose."""

from dataclasses import dataclass
from typing import Any


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _reasoning_text(value: Any) -> str:
    """Read visible reasoning only; signatures and encrypted content stay private."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_reasoning_text(item) for item in value)
    for key in ("summary", "reasoning", "thinking", "reasoning_content", "text", "content"):
        text = _reasoning_text(_field(value, key)) if _field(value, key) is not None else ""
        if text:
            return text
    return ""


@dataclass
class ModelText:
    """Buffer one model call, including thinking tags split across stream chunks."""

    response: str = ""
    thinking: str = ""
    thinking_first: bool = False
    _pending: str = ""
    _in_thinking: bool = False
    _saw_tag: bool = False

    @property
    def has_thinking(self) -> bool:
        return bool(self.thinking) or self._in_thinking

    def _add_thinking(self, text: str) -> None:
        if not self.has_thinking and not self.response:
            self.thinking_first = True
        self.thinking += text

    def add(self, content: Any, additional_kwargs: dict[str, Any]) -> None:
        response_before_chunk = bool(self.response)
        marked_thinking = ""
        if isinstance(content, list):
            for block in content:
                kind = _field(block, "type")
                if kind in ("thinking", "reasoning", "reasoning_content"):
                    text = _reasoning_text(block)
                    marked_thinking += text
                    self._add_thinking(text)
                elif kind == "text":
                    self._add_text(_field(block, "text", ""))
        elif isinstance(content, str):
            self._add_text(content)

        # These are aliases used by different transports. Prefer content blocks
        # when present, and never discard answer text sharing a reasoning delta.
        if not marked_thinking:
            for key in ("reasoning_text", "reasoning_content", "reasoning"):
                text = _reasoning_text(additional_kwargs.get(key))
                if text:
                    if not response_before_chunk and not self.has_thinking:
                        self.thinking_first = True
                    self._add_thinking(text)
                    break

    def _append(self, text: str) -> None:
        if self._in_thinking:
            self._add_thinking(text)
        else:
            self.response += text

    def _add_text(self, text: str) -> None:
        remaining = self._pending + text
        self._pending = ""
        tags = ("<think>", "</think>", "<thinking>", "</thinking>")
        while remaining:
            matches = [(remaining.find(tag), tag) for tag in tags if tag in remaining]
            if matches:
                index, tag = min(matches)
                prefix = remaining[:index]
                if tag.startswith("</") and not self._saw_tag:
                    # Some models omit the opening tag. A closing marker is
                    # still explicit: reclassify the buffered prefix as thinking.
                    self.thinking_first = True
                    self._add_thinking(self.response + prefix)
                    self.response = ""
                else:
                    self._append(prefix)
                self._saw_tag = True
                if not tag.startswith("</") and not self.response:
                    self.thinking_first = True
                self._in_thinking = not tag.startswith("</")
                remaining = remaining[index + len(tag):]
                continue

            # Hold only a possible tag prefix, so a split marker cannot leak.
            length = max(
                (size for tag in tags for size in range(1, len(tag))
                 if remaining.endswith(tag[:size])), default=0,
            )
            if length:
                self._pending = remaining[-length:]
                remaining = remaining[:-length]
            self._append(remaining)
            break

    def finish(self) -> None:
        # An unclosed thinking block is still thinking, including its tail.
        self._append(self._pending)
        self._pending = ""
