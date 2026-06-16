"""Robust conversation summarization middleware for BYOK mode.

LangChain's stock :class:`SummarizationMiddleware` summarizes by first trimming
the slice-to-drop down to ``trim_tokens_to_summarize`` (default 4000) tokens and
then making a *single* model call.  For a coding agent this fails routinely:

* A single large tool result (``read_file`` / ``grep_search`` output) or a
  base64 image injected by ``MultimodalToolResultsMiddleware`` can exceed the
  trim budget on its own, or leave no ``"human"`` boundary in the trim window.
  ``trim_messages`` then returns ``[]`` and the middleware emits the literal
  string ``"Previous conversation was too long to summarize."``
* If the single summary call raises (e.g. the raw fallback messages still
  overflow the context window), it emits ``"Error generating summary: ..."``.

In both cases ``before_model`` has already issued ``RemoveMessage(REMOVE_ALL)``,
so the *entire* conversation history is replaced by that one useless sentence --
the "losing important details" failure mode.

This module fixes that by overriding only the summary *generation* step while
reusing the parent's (genuinely careful) trigger / cutoff / AI-Tool-pairing
logic.  The replacement pipeline:

1. **Sanitize** -- strip base64 images to a placeholder and head/tail-truncate
   oversized message content, so no single message can blow the budget.
2. **Chunk** -- split the drop-slice into pieces sized to the model's own
   context window (via its profile), instead of a fixed 4000-token guess.
3. **Map-reduce** -- summarize each chunk, then summarize the summaries.
4. **Recover, never destroy** -- on a context-length error re-split and retry;
   on a transient error retry a few times; if the model is hopeless, fall back
   to an *extractive* summary built from the real (truncated) messages.

The public guarantee: :meth:`_create_summary` / :meth:`_acreate_summary` always
return a non-empty, bounded summary containing real conversation content.  They
never return an empty string or one of the stock "could not summarize" markers.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import AnyMessage, HumanMessage
from langchain_core.messages.utils import get_buffer_string

from clanker.context import is_context_length_error
from clanker.logging import get_logger

logger = get_logger("agent.summarization")


# Lightweight prompt used to summarize one *segment* of the conversation during
# the map step. Kept terse so partial notes stay small for the reduce step.
MAP_PROMPT = """<role>Conversation Segment Summarizer</role>

You are compressing one segment of a longer software-engineering conversation so
it can be dropped from the context window without losing important details.

Extract, as compact notes, everything that would matter for continuing the work:
- Concrete facts learned (file paths, function/class names, configs, commands).
- Decisions made and the reasoning behind them; options rejected and why.
- Files or resources created, modified, or read, with what changed.
- Errors encountered and their resolution (or current status).
- Tasks completed and tasks still outstanding.

Be specific and preserve identifiers verbatim. Do not editorialize or add
information that is not present. Respond ONLY with the notes.

<segment>
{messages}
</segment>"""


# Prompt used to merge per-segment notes into a single final summary during the
# reduce step. Mirrors the section structure of the stock default prompt so the
# resulting summary looks consistent regardless of which path produced it.
REDUCE_PROMPT = """<role>Conversation Summary Synthesizer</role>

Below are ordered notes extracted from consecutive segments of a
software-engineering conversation. Merge them into a single coherent summary
that will replace the conversation history. Deduplicate, preserve chronology
where it matters, and keep every concrete detail (file paths, identifiers,
decisions, outstanding work). Do not invent anything not present in the notes.

Structure the summary with these sections, writing "None" where empty:

## SESSION INTENT
The user's primary goal and the overall task.

## SUMMARY
The most important context: key facts, choices, conclusions, and the reasoning
behind them, including rejected options.

## ARTIFACTS
Files/resources created, modified, or accessed, with a brief note on each change.

## NEXT STEPS
Specific tasks that remain to achieve the session intent.

Respond ONLY with the structured summary.

<notes>
{messages}
</notes>"""


# Approximate characters-per-token used only for cheap, content-truncation math.
# Token-accurate counting is reserved for chunk packing via ``self.token_counter``.
_CHARS_PER_TOKEN = 4

# Fallback chunk budget (tokens) when the model exposes no profile/context window.
_DEFAULT_CHUNK_TOKEN_TARGET = 12_000

# Hard ceiling and floor for the derived per-chunk token budget.
_MAX_CHUNK_TOKEN_TARGET = 50_000
_MIN_CHUNK_TOKEN_TARGET = 4_000

# Per-message content cap (tokens) applied during sanitization.
_DEFAULT_PER_MESSAGE_TOKEN_CAP = 6_000

# Bound on the extractive fallback output (characters).
_EXTRACTIVE_MAX_CHARS = 12_000
# Per-message snippet length in the extractive fallback (characters).
_EXTRACTIVE_SNIPPET_CHARS = 600
# Header marking an extractive-fallback summary. Used both to build the fallback
# and to detect it after the fact for diagnostics.
_EXTRACTIVE_MARKER = "## SUMMARY (extractive fallback)"

# Safety bound on reduce recursion depth.
_MAX_REDUCE_DEPTH = 5

_IMAGE_PLACEHOLDER = "[image omitted from summary]"
_TRUNCATION_MARKER = "\n... [content truncated for summarization] ...\n"


class RobustSummarizationMiddleware(SummarizationMiddleware):
    """Summarization middleware that never silently discards conversation history.

    Subclasses LangChain's :class:`SummarizationMiddleware`, inheriting all of its
    trigger evaluation and AI/Tool-pair-preserving cutoff logic, and overrides
    only the summary-generation step (:meth:`_create_summary` /
    :meth:`_acreate_summary`) with a sanitize -> chunk -> map-reduce pipeline that
    degrades gracefully instead of returning a placeholder string.
    """

    def __init__(
        self,
        model: Any,
        *,
        chunk_token_target: int | None = None,
        per_message_token_cap: int = _DEFAULT_PER_MESSAGE_TOKEN_CAP,
        max_transient_retries: int = 2,
        **kwargs: Any,
    ) -> None:
        """Initialize the middleware.

        Args:
            model: Chat model used to generate summaries (same model as the agent).
            chunk_token_target: Override for the per-chunk token budget. When
                ``None`` (default) it is derived from the model's context window.
            per_message_token_cap: Maximum tokens of content retained per message
                during sanitization before head/tail truncation kicks in.
            max_transient_retries: Retries for non-context-length model errors
                before falling back to an extractive summary.
            **kwargs: Forwarded to :class:`SummarizationMiddleware` (``trigger``,
                ``keep``, ``summary_prompt``, etc.).
        """
        super().__init__(model, **kwargs)
        self._chunk_token_target = chunk_token_target
        self._per_message_token_cap = per_message_token_cap
        self._max_transient_retries = max_transient_retries

    # ------------------------------------------------------------------
    # Overridden generation entry points (called by parent before_model)
    # ------------------------------------------------------------------
    def _create_summary(self, messages_to_summarize: list[AnyMessage]) -> str:
        """Generate a summary synchronously (overrides parent)."""
        if not messages_to_summarize:
            return "No previous conversation history."

        sanitized = self._sanitize_messages(messages_to_summarize)
        chunks = self._chunk_messages(sanitized)
        logger.info("Summarizing %d messages in %d chunk(s)", len(sanitized), len(chunks))

        if len(chunks) == 1:
            summary = self._summarize_segment(chunks[0], self.summary_prompt)
            result = summary or self._extractive_summary(sanitized)
            self._log_summary_outcome(sanitized, chunks, result)
            return result

        notes = [self._summarize_segment(chunk, MAP_PROMPT) for chunk in chunks]
        notes = [n for n in notes if n.strip()]
        if not notes:
            result = self._extractive_summary(sanitized)
            self._log_summary_outcome(sanitized, chunks, result)
            return result

        reduced = self._reduce_notes(notes)
        result = reduced or self._extractive_summary(sanitized)
        self._log_summary_outcome(sanitized, chunks, result)
        return result

    async def _acreate_summary(self, messages_to_summarize: list[AnyMessage]) -> str:
        """Generate a summary asynchronously (overrides parent)."""
        if not messages_to_summarize:
            return "No previous conversation history."

        sanitized = self._sanitize_messages(messages_to_summarize)
        chunks = self._chunk_messages(sanitized)
        logger.info("Summarizing %d messages in %d chunk(s)", len(sanitized), len(chunks))

        if len(chunks) == 1:
            summary = await self._asummarize_segment(chunks[0], self.summary_prompt)
            result = summary or self._extractive_summary(sanitized)
            self._log_summary_outcome(sanitized, chunks, result)
            return result

        notes: list[str] = []
        for chunk in chunks:
            note = await self._asummarize_segment(chunk, MAP_PROMPT)
            if note.strip():
                notes.append(note)
        if not notes:
            result = self._extractive_summary(sanitized)
            self._log_summary_outcome(sanitized, chunks, result)
            return result

        reduced = await self._areduce_notes(notes)
        result = reduced or self._extractive_summary(sanitized)
        self._log_summary_outcome(sanitized, chunks, result)
        return result

    def _log_summary_outcome(
        self,
        sanitized: list[AnyMessage],
        chunks: list[list[AnyMessage]],
        summary: str,
    ) -> None:
        """Emit diagnostics about a summarization so context loss is traceable.

        Helps distinguish healthy compaction from degradation. The fields:
        - in_msgs:    how many messages were summarized away
        - in_tokens:  approx tokens of that input (what we compressed)
        - out_chars:  length of the produced summary (what replaced them)
        - out_tokens: approx tokens of the summary
        - chunks:     1 = single-pass; >1 = map-reduce (more aggressive)
        - path:       "model" (LLM summary) or "extractive_fallback"

        A WARNING is logged when the extractive fallback fires (the model
        summary failed -> real risk of context loss) or when a multi-message
        input collapsed into a tiny summary (possible erosion). Fallback is
        detected from the summary content so it is caught no matter which
        internal layer produced it.
        """
        used_fallback = summary.lstrip().startswith(_EXTRACTIVE_MARKER)
        try:
            in_tokens = self.token_counter(sanitized)
        except Exception:
            in_tokens = -1
        out_chars = len(summary)
        out_tokens = max(1, out_chars // _CHARS_PER_TOKEN)
        path = "extractive_fallback" if used_fallback else "model"

        logger.info(
            "Summarization outcome: in_msgs=%d in_tokens=%d -> out_chars=%d "
            "out_tokens=%d chunks=%d path=%s",
            len(sanitized), in_tokens, out_chars, out_tokens, len(chunks), path,
        )

        if used_fallback:
            logger.warning(
                "Summarization used EXTRACTIVE FALLBACK (model summary failed) for "
                "%d messages -> context may be degraded. Summary chars=%d",
                len(sanitized), out_chars,
            )
        elif len(sanitized) >= 10 and out_chars < 200:
            logger.warning(
                "Summarization produced a suspiciously short summary: %d messages "
                "collapsed to %d chars -> possible context erosion",
                len(sanitized), out_chars,
            )

    # ------------------------------------------------------------------
    # Map step: summarize a single segment (recovers from overflow)
    # ------------------------------------------------------------------
    def _summarize_segment(self, messages: list[AnyMessage], prompt: str, attempt: int = 0) -> str:
        """Summarize one segment, recovering from context-length/transient errors."""
        if not messages:
            return ""
        try:
            text = self._invoke_summary(messages, prompt)
            return text if text else self._extractive_summary(messages)
        except Exception as exc:  # noqa: BLE001 - we deliberately degrade, never raise
            return self._handle_segment_error(messages, prompt, attempt, exc)

    async def _asummarize_segment(
        self, messages: list[AnyMessage], prompt: str, attempt: int = 0
    ) -> str:
        """Async variant of :meth:`_summarize_segment`."""
        if not messages:
            return ""
        try:
            text = await self._ainvoke_summary(messages, prompt)
            return text if text else self._extractive_summary(messages)
        except Exception as exc:  # noqa: BLE001
            if is_context_length_error(exc):
                if len(messages) > 1:
                    mid = len(messages) // 2
                    left = await self._asummarize_segment(messages[:mid], prompt)
                    right = await self._asummarize_segment(messages[mid:], prompt)
                    return f"{left}\n\n{right}".strip()
                shrunk = self._shrink_single(messages[0])
                if shrunk is not None and attempt == 0:
                    return await self._asummarize_segment([shrunk], prompt, attempt=1)
                return self._extractive_summary(messages)
            if attempt < self._max_transient_retries:
                return await self._asummarize_segment(messages, prompt, attempt=attempt + 1)
            logger.warning("Async summary generation failed after retries: %s", exc)
            return self._extractive_summary(messages)

    def _handle_segment_error(
        self, messages: list[AnyMessage], prompt: str, attempt: int, exc: Exception
    ) -> str:
        """Shared error-recovery policy for the sync map step."""
        if is_context_length_error(exc):
            if len(messages) > 1:
                mid = len(messages) // 2
                left = self._summarize_segment(messages[:mid], prompt)
                right = self._summarize_segment(messages[mid:], prompt)
                return f"{left}\n\n{right}".strip()
            shrunk = self._shrink_single(messages[0])
            if shrunk is not None and attempt == 0:
                return self._summarize_segment([shrunk], prompt, attempt=1)
            return self._extractive_summary(messages)
        if attempt < self._max_transient_retries:
            return self._summarize_segment(messages, prompt, attempt=attempt + 1)
        logger.warning("Summary generation failed after retries: %s", exc)
        return self._extractive_summary(messages)

    # ------------------------------------------------------------------
    # Reduce step: merge per-segment notes into one summary
    # ------------------------------------------------------------------
    def _reduce_notes(self, notes: list[str], depth: int = 0) -> str:
        """Merge notes into a final summary, re-reducing if they don't fit."""
        if not notes:
            return ""
        if len(notes) == 1:
            return notes[0]

        note_messages = [HumanMessage(content=n) for n in notes]
        chunks = self._chunk_messages(note_messages)

        if len(chunks) == 1:
            return self._summarize_segment(chunks[0], REDUCE_PROMPT)

        # No progress (every note is its own chunk) or recursion too deep:
        # collapse deterministically so we always terminate.
        if len(chunks) >= len(notes) or depth >= _MAX_REDUCE_DEPTH:
            return self._truncate_text("\n\n".join(notes), _EXTRACTIVE_MAX_CHARS)

        reduced = [self._summarize_segment(chunk, REDUCE_PROMPT) for chunk in chunks]
        reduced = [r for r in reduced if r.strip()]
        return self._reduce_notes(reduced, depth=depth + 1)

    async def _areduce_notes(self, notes: list[str], depth: int = 0) -> str:
        """Async variant of :meth:`_reduce_notes`."""
        if not notes:
            return ""
        if len(notes) == 1:
            return notes[0]

        note_messages = [HumanMessage(content=n) for n in notes]
        chunks = self._chunk_messages(note_messages)

        if len(chunks) == 1:
            return await self._asummarize_segment(chunks[0], REDUCE_PROMPT)

        if len(chunks) >= len(notes) or depth >= _MAX_REDUCE_DEPTH:
            return self._truncate_text("\n\n".join(notes), _EXTRACTIVE_MAX_CHARS)

        reduced: list[str] = []
        for chunk in chunks:
            r = await self._asummarize_segment(chunk, REDUCE_PROMPT)
            if r.strip():
                reduced.append(r)
        return await self._areduce_notes(reduced, depth=depth + 1)

    # ------------------------------------------------------------------
    # Model invocation
    # ------------------------------------------------------------------
    def _invoke_summary(self, messages: list[AnyMessage], prompt: str) -> str:
        """Format the segment and make a single summary model call (sync)."""
        formatted = get_buffer_string(messages)
        rendered = prompt.format(messages=formatted).rstrip()
        response = self.model.invoke(rendered, config={"metadata": {"lc_source": "summarization"}})
        return response.text.strip()

    async def _ainvoke_summary(self, messages: list[AnyMessage], prompt: str) -> str:
        """Format the segment and make a single summary model call (async)."""
        formatted = get_buffer_string(messages)
        rendered = prompt.format(messages=formatted).rstrip()
        response = await self.model.ainvoke(
            rendered, config={"metadata": {"lc_source": "summarization"}}
        )
        return response.text.strip()

    # ------------------------------------------------------------------
    # Sanitization (pure)
    # ------------------------------------------------------------------
    def _sanitize_messages(self, messages: list[AnyMessage]) -> list[AnyMessage]:
        """Return copies with images stripped and oversized content truncated."""
        sanitized: list[AnyMessage] = []
        for message in messages:
            new_content = self._sanitize_content(message.content)
            if new_content is message.content:
                sanitized.append(message)
                continue
            try:
                sanitized.append(message.model_copy(update={"content": new_content}))
            except Exception:  # noqa: BLE001 - never let copying break summarization
                sanitized.append(message)
        return sanitized

    def _sanitize_content(self, content: Any) -> Any:
        """Normalize message content to bounded, image-free text.

        Returns the original object unchanged when no sanitization is needed so
        callers can cheaply detect "nothing changed".
        """
        cap_chars = self._per_message_token_cap * _CHARS_PER_TOKEN

        if isinstance(content, str):
            if len(content) <= cap_chars:
                return content
            return self._truncate_text(content, cap_chars)

        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict):
                    block_type = block.get("type")
                    if block_type in ("image_url", "image", "input_image"):
                        parts.append(_IMAGE_PLACEHOLDER)
                    elif block_type == "text":
                        parts.append(str(block.get("text", "")))
                    else:
                        # Unknown structured block: keep a compact textual hint.
                        text = block.get("text")
                        parts.append(str(text) if text is not None else f"[{block_type}]")
                else:
                    parts.append(str(block))
            joined = "\n".join(p for p in parts if p)
            if len(joined) > cap_chars:
                joined = self._truncate_text(joined, cap_chars)
            return joined

        return content

    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        """Head/tail truncate text, keeping both ends around a marker."""
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        budget = max(max_chars - len(_TRUNCATION_MARKER), 1)
        head = (budget * 3) // 5
        tail = budget - head
        if tail <= 0:
            return text[:budget] + _TRUNCATION_MARKER
        return text[:head] + _TRUNCATION_MARKER + text[-tail:]

    def _shrink_single(self, message: AnyMessage) -> AnyMessage | None:
        """Aggressively shrink a single oversized message; ``None`` if already tiny."""
        text = message.content if isinstance(message.content, str) else get_buffer_string([message])
        target_chars = (_MIN_CHUNK_TOKEN_TARGET // 2) * _CHARS_PER_TOKEN
        if len(text) <= target_chars:
            return None
        try:
            return message.model_copy(update={"content": self._truncate_text(text, target_chars)})
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # Chunking & budget (pure)
    # ------------------------------------------------------------------
    def _chunk_budget(self) -> int:
        """Per-chunk token budget, derived from the model window when available."""
        if self._chunk_token_target is not None:
            return max(self._chunk_token_target, 1)
        limit: int | None
        try:
            limit = self._get_profile_limits()
        except Exception:  # noqa: BLE001
            limit = None
        if isinstance(limit, int) and limit > 0:
            return max(_MIN_CHUNK_TOKEN_TARGET, min(int(limit * 0.5), _MAX_CHUNK_TOKEN_TARGET))
        return _DEFAULT_CHUNK_TOKEN_TARGET

    def _chunk_messages(self, messages: list[AnyMessage]) -> list[list[AnyMessage]]:
        """Pack messages into chunks that each fit the per-chunk token budget."""
        if not messages:
            return []
        budget = self._chunk_budget()
        chunks: list[list[AnyMessage]] = []
        current: list[AnyMessage] = []
        current_tokens = 0
        for message in messages:
            tokens = self.token_counter([message])
            if current and current_tokens + tokens > budget:
                chunks.append(current)
                current = []
                current_tokens = 0
            current.append(message)
            current_tokens += tokens
        if current:
            chunks.append(current)
        return chunks

    # ------------------------------------------------------------------
    # Extractive fallback (pure, never empty for non-empty input)
    # ------------------------------------------------------------------
    def _extractive_summary(self, messages: list[AnyMessage]) -> str:
        """Build a summary from the real messages when the model can't be used.

        This preserves actual conversation content (truncated) rather than
        discarding it, which is the whole point of the fix.
        """
        header = (
            f"{_EXTRACTIVE_MARKER}\n"
            "Automatic model summarization was unavailable; the conversation was "
            "condensed by extracting message content directly:\n"
        )
        lines: list[str] = []
        for message in messages:
            role = self._role_of(message)
            text = (
                message.content
                if isinstance(message.content, str)
                else get_buffer_string([message])
            )
            text = " ".join(text.split())
            if len(text) > _EXTRACTIVE_SNIPPET_CHARS:
                text = text[:_EXTRACTIVE_SNIPPET_CHARS] + " ..."
            if text:
                lines.append(f"- {role}: {text}")
        body = "\n".join(lines) if lines else "- (no extractable text content)"
        return self._truncate_text(header + body, _EXTRACTIVE_MAX_CHARS)

    @staticmethod
    def _role_of(message: AnyMessage) -> str:
        """Human-readable role label for a message."""
        mapping = {"human": "User", "ai": "Assistant", "tool": "Tool", "system": "System"}
        return mapping.get(getattr(message, "type", ""), getattr(message, "type", "Message"))
