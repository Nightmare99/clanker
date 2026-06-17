"""Tests for the per-model stream-chunk timeout (reasoning-pause tolerance)."""

from __future__ import annotations

import pytest

from clanker.config.models import (
    DEFAULT_STREAM_CHUNK_TIMEOUT,
    ModelConfig,
    _resolve_stream_chunk_timeout,
)


def _cfg(timeout, provider="OpenAI"):
    return ModelConfig(
        name="m",
        provider=provider,
        model="gpt-4o",
        stream_chunk_timeout=timeout,
    )


class TestResolveStreamChunkTimeout:
    def test_unset_uses_default(self):
        assert _resolve_stream_chunk_timeout(_cfg(None)) == DEFAULT_STREAM_CHUNK_TIMEOUT

    def test_default_is_above_stock_120s(self):
        # The whole point: tolerate long silent reasoning pauses.
        assert DEFAULT_STREAM_CHUNK_TIMEOUT > 120

    def test_zero_disables(self):
        assert _resolve_stream_chunk_timeout(_cfg(0)) is None

    def test_negative_disables(self):
        assert _resolve_stream_chunk_timeout(_cfg(-5)) is None

    def test_explicit_value_passthrough(self):
        assert _resolve_stream_chunk_timeout(_cfg(300)) == 300


class TestModelConfigField:
    def test_field_defaults_none(self):
        cfg = ModelConfig(name="m", provider="OpenAI", model="gpt-4o")
        assert cfg.stream_chunk_timeout is None

    def test_field_roundtrips(self):
        cfg = ModelConfig(name="m", provider="OpenAI", stream_chunk_timeout=900)
        dumped = cfg.model_dump()
        assert dumped["stream_chunk_timeout"] == 900
        assert ModelConfig(**dumped).stream_chunk_timeout == 900


def _langchain_openai_available() -> bool:
    try:
        import langchain_openai  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _langchain_openai_available(), reason="langchain_openai not installed")
class TestConstruction:
    def test_openai_builds_with_timeout(self, monkeypatch):
        from clanker.config.models import create_llm_from_config

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        # High-reasoning config like the one that tripped the 120s timeout.
        cfg = ModelConfig(
            name="copilot-opus",
            provider="OpenAI",
            model="claude-opus-4.8",
            reasoning_effort="xhigh",
            max_input_tokens=200000,
        )
        # Must construct without error; the kwarg is accepted by ChatOpenAI.
        model = create_llm_from_config(cfg)
        assert model is not None

    def test_openai_builds_with_timeout_disabled(self, monkeypatch):
        from clanker.config.models import create_llm_from_config

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg = ModelConfig(name="m", provider="OpenAI", model="gpt-4o", stream_chunk_timeout=0)
        model = create_llm_from_config(cfg)
        assert model is not None
