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
            name="opus-reasoning",
            provider="OpenAI",
            model="claude-opus-4.8",
            reasoning_effort="xhigh",
            max_input_tokens=200000,
        )
        # Must construct without error and without leaking a bad kwarg.
        model = create_llm_from_config(cfg)
        assert model is not None

    def test_openai_builds_with_timeout_disabled(self, monkeypatch):
        from clanker.config.models import create_llm_from_config

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg = ModelConfig(name="m", provider="OpenAI", model="gpt-4o", stream_chunk_timeout=0)
        model = create_llm_from_config(cfg)
        assert model is not None

    def test_timeout_never_leaks_into_model_kwargs(self, monkeypatch):
        """Regression: stream_chunk_timeout must NOT reach model_kwargs.

        On langchain-openai versions without the field, a leaked kwarg gets
        forwarded to the API call and breaks every request ("unexpected keyword
        argument"). It must go via the field (newer) or the env var (older),
        never model_kwargs.
        """
        from langchain_openai import ChatOpenAI

        from clanker.config.models import create_llm_from_config

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg = ModelConfig(name="m", provider="OpenAI", model="gpt-4o", stream_chunk_timeout=600)
        model = create_llm_from_config(cfg)

        leaked = "stream_chunk_timeout" in (getattr(model, "model_kwargs", None) or {})
        assert not leaked, "stream_chunk_timeout leaked into model_kwargs (breaks API calls)"

        # On a version without the field, the env var carries the value instead.
        if "stream_chunk_timeout" not in ChatOpenAI.model_fields:
            import os

            assert os.environ.get("LANGCHAIN_OPENAI_STREAM_CHUNK_TIMEOUT_S") == "600"

    def test_apply_uses_field_when_supported(self, monkeypatch):
        """When the class exposes the field, the kwarg path is used (not env)."""
        from clanker.config.models import _apply_stream_chunk_timeout

        class FakeChat:
            model_fields = {"stream_chunk_timeout": object()}

        kwargs: dict = {}
        cfg = ModelConfig(name="m", provider="OpenAI", stream_chunk_timeout=300)
        _apply_stream_chunk_timeout(FakeChat, kwargs, cfg)
        assert kwargs["stream_chunk_timeout"] == 300

    def test_apply_uses_env_when_field_absent(self, monkeypatch):
        """When the class lacks the field, the env var is set and kwargs stays clean."""
        import os

        from clanker.config.models import _apply_stream_chunk_timeout

        class FakeChat:
            model_fields: dict = {}

        monkeypatch.delenv("LANGCHAIN_OPENAI_STREAM_CHUNK_TIMEOUT_S", raising=False)
        kwargs: dict = {}
        cfg = ModelConfig(name="m", provider="OpenAI", stream_chunk_timeout=300)
        _apply_stream_chunk_timeout(FakeChat, kwargs, cfg)
        assert "stream_chunk_timeout" not in kwargs
        assert os.environ["LANGCHAIN_OPENAI_STREAM_CHUNK_TIMEOUT_S"] == "300"
