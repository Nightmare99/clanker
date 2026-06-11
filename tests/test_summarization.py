"""Tests for RobustSummarizationMiddleware (BYOK mode).

These tests exercise the summary-generation pipeline directly with a fake model,
so they need no API keys or network access. They are skipped if langchain is not
installed (mirroring tests/test_agent.py).
"""

from __future__ import annotations

import pytest


def _langchain_available() -> bool:
    try:
        import langchain_core  # noqa: F401

        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _langchain_available(), reason="langchain not installed")


# Junk markers the stock middleware emits that we must never reproduce.
_JUNK = (
    "",
    "Previous conversation was too long to summarize.",
)


class FakeResponse:
    """Minimal stand-in for a chat model response (exposes ``.text``)."""

    def __init__(self, text: str) -> None:
        self.text = text


class FakeModel:
    """Configurable fake chat model.

    Args:
        responder: ``(rendered_prompt, call_number) -> str``. May raise to
            simulate provider errors. Defaults to returning ``"GOOD_SUMMARY"``.
    """

    def __init__(self, responder=None) -> None:
        self.calls: list[str] = []
        self._responder = responder or (lambda _prompt, _n: "GOOD_SUMMARY")
        # Custom token_counter is supplied to the middleware, so the parent never
        # introspects these; present only for realism / safety.
        self._llm_type = "fake-chat"
        self.profile = {"max_input_tokens": 100_000}

    def invoke(self, prompt, config=None):  # noqa: ANN001
        n = len(self.calls)
        self.calls.append(prompt)
        return FakeResponse(self._responder(prompt, n))

    async def ainvoke(self, prompt, config=None):  # noqa: ANN001
        n = len(self.calls)
        self.calls.append(prompt)
        return FakeResponse(self._responder(prompt, n))


def _char_token_counter(messages) -> int:
    """Deterministic token counter: ~1 token per 4 chars of content."""
    total = 0
    for m in messages:
        content = m.content if isinstance(m.content, str) else str(m.content)
        total += max(1, len(content) // 4 + 1)
    return total


def _build(model: FakeModel, *, chunk_token_target: int = 1_000_000, **kwargs):
    """Construct the middleware with deterministic, profile-free settings."""
    from clanker.agent.summarization import RobustSummarizationMiddleware

    return RobustSummarizationMiddleware(
        model=model,
        trigger=("messages", 100),
        keep=("messages", 10),
        token_counter=_char_token_counter,
        chunk_token_target=chunk_token_target,
        **kwargs,
    )


def _messages(*pairs):
    """Build messages from (kind, content) pairs. kind in {h, a, t, s}."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    out = []
    for kind, content in pairs:
        if kind == "h":
            out.append(HumanMessage(content=content))
        elif kind == "a":
            out.append(AIMessage(content=content))
        elif kind == "s":
            out.append(SystemMessage(content=content))
        elif kind == "t":
            out.append(ToolMessage(content=content, tool_call_id="tc1"))
        else:  # pragma: no cover - test author error
            raise ValueError(kind)
    return out


# ---------------------------------------------------------------------------
# Subclassing / inheritance
# ---------------------------------------------------------------------------
class TestInheritance:
    def test_is_summarization_middleware(self) -> None:
        from langchain.agents.middleware import SummarizationMiddleware

        mw = _build(FakeModel())
        assert isinstance(mw, SummarizationMiddleware)
        # Parent trigger/cutoff machinery is inherited, not reimplemented.
        assert hasattr(mw, "before_model")
        assert hasattr(mw, "_find_safe_cutoff_point")


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------
class TestSanitization:
    def test_short_string_unchanged(self) -> None:
        mw = _build(FakeModel())
        assert mw._sanitize_content("hello world") == "hello world"

    def test_long_string_truncated_with_marker(self) -> None:
        mw = _build(FakeModel(), per_message_token_cap=100)  # cap ~400 chars
        text = "A" * 5000
        out = mw._sanitize_content(text)
        assert len(out) < len(text)
        assert "truncated for summarization" in out
        # Head and tail are both preserved.
        assert out.startswith("A")
        assert out.endswith("A")

    def test_image_block_stripped(self) -> None:
        mw = _build(FakeModel())
        content = [
            {"type": "text", "text": "see image"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAABBBBCCCC"}},
        ]
        out = mw._sanitize_content(content)
        assert "image omitted" in out
        assert "base64" not in out
        assert "AAAABBBB" not in out
        assert "see image" in out

    def test_sanitize_messages_returns_copies(self) -> None:
        mw = _build(FakeModel(), per_message_token_cap=10)
        msgs = _messages(("h", "B" * 5000))
        sanitized = mw._sanitize_messages(msgs)
        # Original is untouched; sanitized copy is shorter.
        assert len(msgs[0].content) == 5000
        assert len(sanitized[0].content) < 5000

    def test_truncate_text_bounds(self) -> None:
        mw = _build(FakeModel())
        out = mw._truncate_text("X" * 10000, 1000)
        assert len(out) <= 1000


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
class TestChunking:
    def test_splits_into_multiple_chunks(self) -> None:
        # Each message ~ 400 chars -> ~101 tokens. Budget 250 -> 2 per chunk.
        mw = _build(FakeModel(), chunk_token_target=250)
        msgs = _messages(("h", "A" * 400), ("a", "B" * 400), ("h", "C" * 400), ("a", "D" * 400))
        chunks = mw._chunk_messages(msgs)
        assert len(chunks) == 2
        assert all(len(c) == 2 for c in chunks)

    def test_single_chunk_when_budget_large(self) -> None:
        mw = _build(FakeModel(), chunk_token_target=1_000_000)
        msgs = _messages(("h", "x"), ("a", "y"), ("h", "z"))
        assert len(mw._chunk_messages(msgs)) == 1

    def test_empty_messages(self) -> None:
        mw = _build(FakeModel())
        assert mw._chunk_messages([]) == []


# ---------------------------------------------------------------------------
# Happy-path summary generation
# ---------------------------------------------------------------------------
class TestCreateSummary:
    def test_empty_input(self) -> None:
        mw = _build(FakeModel())
        assert mw._create_summary([]) == "No previous conversation history."

    def test_single_chunk_one_call(self) -> None:
        model = FakeModel()
        mw = _build(model, chunk_token_target=1_000_000)
        result = mw._create_summary(_messages(("h", "do the thing"), ("a", "done")))
        assert result == "GOOD_SUMMARY"
        assert len(model.calls) == 1

    def test_map_reduce_multiple_chunks(self) -> None:
        model = FakeModel()
        mw = _build(model, chunk_token_target=250)
        msgs = _messages(("h", "A" * 400), ("a", "B" * 400), ("h", "C" * 400), ("a", "D" * 400))
        result = mw._create_summary(msgs)
        assert result == "GOOD_SUMMARY"
        # 2 map calls + 1 reduce call.
        assert len(model.calls) == 3
        # The map step used MAP_PROMPT and the reduce step used REDUCE_PROMPT.
        assert any("Conversation Segment Summarizer" in c for c in model.calls)
        assert any("Conversation Summary Synthesizer" in c for c in model.calls)


# ---------------------------------------------------------------------------
# Error recovery
# ---------------------------------------------------------------------------
class TestErrorRecovery:
    def test_transient_error_then_success(self) -> None:
        def responder(_prompt, n):
            if n == 0:
                raise RuntimeError("temporary network blip")
            return "RECOVERED"

        model = FakeModel(responder)
        mw = _build(model, chunk_token_target=1_000_000, max_transient_retries=2)
        result = mw._create_summary(_messages(("h", "hello")))
        assert result == "RECOVERED"
        assert len(model.calls) == 2  # one failure, one success

    def test_context_length_error_triggers_resplit(self) -> None:
        # Raise a context-length error whenever both messages are in one prompt;
        # succeed once the slice is small enough.
        def responder(prompt, _n):
            if "FIRST" in prompt and "SECOND" in prompt:
                raise RuntimeError("prompt is too long: maximum context length exceeded")
            return "PARTIAL"

        model = FakeModel(responder)
        mw = _build(model, chunk_token_target=1_000_000)
        msgs = _messages(("h", "FIRST message"), ("a", "SECOND message"))
        result = mw._create_summary(msgs)
        # Both halves summarized and combined; never the junk string.
        assert "PARTIAL" in result
        assert result not in _JUNK

    def test_hopeless_model_falls_back_to_extractive(self) -> None:
        def responder(_prompt, _n):
            raise RuntimeError("model is on fire")

        model = FakeModel(responder)
        mw = _build(model, chunk_token_target=1_000_000)
        msgs = _messages(
            ("h", "please refactor the parser in src/clanker/parser.py"),
            ("a", "I updated parse_tokens and added a test"),
        )
        result = mw._create_summary(msgs)
        # Extractive fallback preserves real content rather than discarding it.
        assert "extractive fallback" in result
        assert "src/clanker/parser.py" in result
        assert "parse_tokens" in result
        assert result not in _JUNK

    def test_context_error_on_single_giant_message(self) -> None:
        def responder(_prompt, _n):
            raise RuntimeError("input is too long")

        model = FakeModel(responder)
        mw = _build(model, chunk_token_target=1_000_000)
        msgs = _messages(("t", "UNIQUE_TOKEN " + "Z" * 40000))
        result = mw._create_summary(msgs)
        assert result not in _JUNK
        assert "UNIQUE_TOKEN" in result  # real content survives via extraction


# ---------------------------------------------------------------------------
# The core invariant
# ---------------------------------------------------------------------------
class TestInvariant:
    @pytest.mark.parametrize(
        "responder",
        [
            lambda _p, _n: "GOOD_SUMMARY",
            lambda _p, _n: (_ for _ in ()).throw(RuntimeError("prompt is too long")),
            lambda _p, _n: (_ for _ in ()).throw(RuntimeError("boom")),
            lambda _p, _n: "",  # model returns empty -> must still not be junk
        ],
    )
    def test_never_returns_junk_for_nonempty_input(self, responder) -> None:
        model = FakeModel(responder)
        mw = _build(model, chunk_token_target=300)
        msgs = _messages(
            ("h", "MARKER_ONE " + "a" * 400),
            ("a", "MARKER_TWO " + "b" * 400),
        )
        result = mw._create_summary(msgs)
        assert result not in _JUNK
        assert not result.startswith("Error generating summary")
        assert result.strip() != ""


# ---------------------------------------------------------------------------
# Async path
# ---------------------------------------------------------------------------
class TestAsync:
    async def test_async_single_chunk(self) -> None:
        model = FakeModel()
        mw = _build(model, chunk_token_target=1_000_000)
        result = await mw._acreate_summary(_messages(("h", "hi"), ("a", "yo")))
        assert result == "GOOD_SUMMARY"
        assert len(model.calls) == 1

    async def test_async_map_reduce(self) -> None:
        model = FakeModel()
        mw = _build(model, chunk_token_target=250)
        msgs = _messages(("h", "A" * 400), ("a", "B" * 400), ("h", "C" * 400), ("a", "D" * 400))
        result = await mw._acreate_summary(msgs)
        assert result == "GOOD_SUMMARY"
        assert len(model.calls) == 3

    async def test_async_hopeless_model_extractive(self) -> None:
        def responder(_prompt, _n):
            raise RuntimeError("kaput")

        model = FakeModel(responder)
        mw = _build(model, chunk_token_target=1_000_000)
        result = await mw._acreate_summary(_messages(("h", "find DISTINCT_MARKER")))
        assert "DISTINCT_MARKER" in result
        assert result not in _JUNK

    async def test_async_empty(self) -> None:
        mw = _build(FakeModel())
        assert await mw._acreate_summary([]) == "No previous conversation history."
