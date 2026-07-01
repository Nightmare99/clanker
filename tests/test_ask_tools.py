"""Tests for the ask_user tool and the select_options selector."""

from __future__ import annotations

import builtins

import pytest


# ----------------------------------------------------------------------
# select_options fallback (non-TTY) parsing
# ----------------------------------------------------------------------
def _force_non_tty(monkeypatch):
    """Make _stdin_is_interactive() return False so the numbered path runs."""
    from clanker.ui import prompts

    monkeypatch.setattr(prompts, "_stdin_is_interactive", lambda: False)


def _feed_inputs(monkeypatch, answers):
    """Feed a queue of input() responses."""
    it = iter(answers)
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(it))


class TestSelectFallback:
    def test_single_select(self, monkeypatch, capsys):
        from clanker.ui.prompts import select_options

        _force_non_tty(monkeypatch)
        _feed_inputs(monkeypatch, ["2"])
        result = select_options("Env?", ["staging", "production", "both"])
        assert result == {"selected": ["production"], "cancelled": False}

    def test_multi_select(self, monkeypatch):
        from clanker.ui.prompts import select_options

        _force_non_tty(monkeypatch)
        _feed_inputs(monkeypatch, ["1,3"])
        result = select_options("Svcs?", ["auth", "billing", "search"], multi_select=True)
        assert result == {"selected": ["auth", "search"], "cancelled": False}

    def test_cancel_with_zero(self, monkeypatch):
        from clanker.ui.prompts import select_options

        _force_non_tty(monkeypatch)
        _feed_inputs(monkeypatch, ["0"])
        assert select_options("Q", ["a", "b"]) == {"selected": [], "cancelled": True}

    def test_cancel_with_empty(self, monkeypatch):
        from clanker.ui.prompts import select_options

        _force_non_tty(monkeypatch)
        _feed_inputs(monkeypatch, [""])
        assert select_options("Q", ["a", "b"])["cancelled"] is True

    def test_other_via_letter(self, monkeypatch):
        from clanker.ui.prompts import select_options

        _force_non_tty(monkeypatch)
        _feed_inputs(monkeypatch, ["o", "my custom answer"])
        result = select_options("Q", ["a", "b"])
        assert result == {"selected": ["my custom answer"], "cancelled": False}

    def test_other_via_number(self, monkeypatch):
        from clanker.ui.prompts import select_options

        _force_non_tty(monkeypatch)
        # options a,b -> "Other" is number 3
        _feed_inputs(monkeypatch, ["3", "typed value"])
        result = select_options("Q", ["a", "b"])
        assert result == {"selected": ["typed value"], "cancelled": False}

    def test_out_of_range_is_cancelled(self, monkeypatch):
        from clanker.ui.prompts import select_options

        _force_non_tty(monkeypatch)
        _feed_inputs(monkeypatch, ["9"])
        assert select_options("Q", ["a", "b"], allow_other=False)["cancelled"] is True

    def test_eof_is_cancel(self, monkeypatch):
        from clanker.ui.prompts import select_options

        _force_non_tty(monkeypatch)

        def raise_eof(*a, **k):
            raise EOFError

        monkeypatch.setattr(builtins, "input", raise_eof)
        assert select_options("Q", ["a", "b"])["cancelled"] is True


# ----------------------------------------------------------------------
# ask_user tool
# ----------------------------------------------------------------------
def _langchain_available() -> bool:
    try:
        import langchain_core  # noqa: F401

        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _langchain_available(), reason="langchain not installed")


class TestAskUserValidation:
    def test_empty_options(self):
        from clanker.tools.ask_tools import ask_user

        out = ask_user.invoke({"question": "Q", "options": []})
        assert out["ok"] is False
        assert "options" in out["error"]

    def test_blank_question(self):
        from clanker.tools.ask_tools import ask_user

        out = ask_user.invoke({"question": "   ", "options": ["a"]})
        assert out["ok"] is False
        assert "question" in out["error"]

    def test_too_many_options(self):
        from clanker.tools.ask_tools import ask_user

        out = ask_user.invoke({"question": "Q", "options": [str(i) for i in range(11)]})
        assert out["ok"] is False
        assert "too many" in out["error"]

    def test_options_stringified(self):
        from clanker.tools import ask_tools

        captured = {}

        def fake(question, options, **kw):
            captured["options"] = options
            return {"selected": [options[0]], "cancelled": False}

        ask_tools.set_ask_callback(fake)
        try:
            out = ask_tools.ask_user.invoke({"question": "Q", "options": ["10", "20"]})
        finally:
            ask_tools.set_ask_callback(None)
        assert out["ok"] is True
        assert captured["options"] == ["10", "20"]


class TestAskUserCallback:
    def test_uses_registered_callback(self):
        from clanker.tools import ask_tools

        def fake(question, options, *, multi_select, allow_other, allow_cancel):
            return {"selected": [options[1]], "cancelled": False}

        ask_tools.set_ask_callback(fake)
        try:
            out = ask_tools.ask_user.invoke({"question": "Env?", "options": ["staging", "prod"]})
        finally:
            ask_tools.set_ask_callback(None)
        assert out == {"ok": True, "selected": ["prod"], "cancelled": False}

    def test_cancel_result(self):
        from clanker.tools import ask_tools

        ask_tools.set_ask_callback(lambda *a, **k: {"selected": [], "cancelled": True})
        try:
            out = ask_tools.ask_user.invoke({"question": "Q", "options": ["a", "b"]})
        finally:
            ask_tools.set_ask_callback(None)
        assert out == {"ok": True, "selected": [], "cancelled": True}

    def test_empty_selection_counts_as_cancelled(self):
        from clanker.tools import ask_tools

        # A callback returning nothing selected -> treated as cancelled.
        ask_tools.set_ask_callback(lambda *a, **k: {"selected": [], "cancelled": False})
        try:
            out = ask_tools.ask_user.invoke({"question": "Q", "options": ["a"]})
        finally:
            ask_tools.set_ask_callback(None)
        assert out["cancelled"] is True

    def test_callback_exception_returns_error(self):
        from clanker.tools import ask_tools

        def boom(*a, **k):
            raise RuntimeError("ui exploded")

        ask_tools.set_ask_callback(boom)
        try:
            out = ask_tools.ask_user.invoke({"question": "Q", "options": ["a"]})
        finally:
            ask_tools.set_ask_callback(None)
        assert out["ok"] is False
        assert "could not collect" in out["error"]

    def test_falls_back_when_no_callback(self, monkeypatch):
        from clanker.tools import ask_tools
        from clanker.ui import prompts

        ask_tools.set_ask_callback(None)
        monkeypatch.setattr(prompts, "_stdin_is_interactive", lambda: False)
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "1")
        out = ask_tools.ask_user.invoke({"question": "Q", "options": ["x", "y"]})
        assert out == {"ok": True, "selected": ["x"], "cancelled": False}


class TestAskUserRegistration:
    def test_registered_in_tool_registry(self):
        from clanker.tools import get_tools

        assert "ask_user" in [t.name for t in get_tools()]
