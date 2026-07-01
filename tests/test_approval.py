"""Tests for the bash command approval flow (non-yolo mode)."""

from __future__ import annotations

import builtins

import pytest

from clanker.tools import bash_tools
from clanker.tools.bash_tools import (
    _APPROVE_ALWAYS,
    _APPROVE_NO,
    _APPROVE_YES,
    CommandRejectedError,
    prompt_for_approval,
    set_approval_callback,
)


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset yolo mode and the approval callback around each test."""
    from clanker import runtime

    runtime._yolo_mode = False
    set_approval_callback(None)
    yield
    runtime._yolo_mode = False
    set_approval_callback(None)


def _callback_returning(label):
    """An approval callback that always selects ``label``."""
    return lambda question, options, *, preface=None: {"selected": [label], "cancelled": False}


class TestApprovalViaCallback:
    def test_yes_executes(self):
        from clanker import runtime

        set_approval_callback(_callback_returning(_APPROVE_YES))
        assert prompt_for_approval("npm test") is True
        assert runtime.is_yolo_mode() is False  # yolo unchanged

    def test_always_enables_yolo(self):
        from clanker import runtime

        set_approval_callback(_callback_returning(_APPROVE_ALWAYS))
        assert prompt_for_approval("npm test") is True
        assert runtime.is_yolo_mode() is True  # session auto-approve on

    def test_no_rejects(self):
        set_approval_callback(_callback_returning(_APPROVE_NO))
        with pytest.raises(CommandRejectedError):
            prompt_for_approval("rm -rf build")

    def test_cancelled_rejects(self):
        set_approval_callback(lambda q, o, *, preface=None: {"selected": [], "cancelled": True})
        with pytest.raises(CommandRejectedError):
            prompt_for_approval("npm test")

    def test_callback_exception_rejects(self):
        def boom(q, o, *, preface=None):
            raise RuntimeError("ui broke")

        set_approval_callback(boom)
        with pytest.raises(CommandRejectedError):
            prompt_for_approval("npm test")

    def test_callback_receives_command_in_preface(self):
        captured = {}

        def cb(question, options, *, preface=None):
            captured["preface"] = preface
            captured["options"] = options
            return {"selected": [_APPROVE_YES], "cancelled": False}

        set_approval_callback(cb)
        prompt_for_approval("kubectl get pods")
        assert "kubectl get pods" in captured["preface"]
        assert _APPROVE_YES in captured["options"]
        assert _APPROVE_ALWAYS in captured["options"]
        assert _APPROVE_NO in captured["options"]


class TestApprovalFallback:
    """No callback registered -> numbered stdin prompt."""

    def _feed(self, monkeypatch, answer):
        monkeypatch.setattr(builtins, "input", lambda *a, **k: answer)

    def test_choice_1_yes(self, monkeypatch):
        from clanker import runtime

        self._feed(monkeypatch, "1")
        assert prompt_for_approval("echo hi") is True
        assert runtime.is_yolo_mode() is False

    def test_choice_2_always(self, monkeypatch):
        from clanker import runtime

        self._feed(monkeypatch, "2")
        assert prompt_for_approval("echo hi") is True
        assert runtime.is_yolo_mode() is True

    def test_choice_3_rejects(self, monkeypatch):
        self._feed(monkeypatch, "3")
        with pytest.raises(CommandRejectedError):
            prompt_for_approval("echo hi")

    def test_blank_rejects(self, monkeypatch):
        self._feed(monkeypatch, "")
        with pytest.raises(CommandRejectedError):
            prompt_for_approval("echo hi")

    def test_out_of_range_rejects(self, monkeypatch):
        self._feed(monkeypatch, "9")
        with pytest.raises(CommandRejectedError):
            prompt_for_approval("echo hi")

    def test_eof_rejects(self, monkeypatch):
        def raise_eof(*a, **k):
            raise EOFError

        monkeypatch.setattr(builtins, "input", raise_eof)
        with pytest.raises(CommandRejectedError):
            prompt_for_approval("echo hi")


class TestRunSafetyChecks:
    """run_safety_checks integrates the approval gate."""

    def test_approve_returns_none(self, monkeypatch):
        from clanker.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings.safety, "require_confirmation", True)
        monkeypatch.setattr(settings.safety, "sandbox_commands", False)
        set_approval_callback(_callback_returning(_APPROVE_YES))
        assert bash_tools.run_safety_checks("echo hi") is None

    def test_reject_raises(self, monkeypatch):
        from clanker.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings.safety, "require_confirmation", True)
        monkeypatch.setattr(settings.safety, "sandbox_commands", False)
        set_approval_callback(_callback_returning(_APPROVE_NO))
        with pytest.raises(CommandRejectedError):
            bash_tools.run_safety_checks("echo hi")
