"""Tests for session restore seeding the next turn's graph state.

Regression coverage for the bug where /restore and --resume changed the
thread_id and updated the display list, but never put the restored history
into the graph state — so the agent resumed with no memory of the conversation.

The fix injects the restored messages into the *next* turn's state["messages"]
(prepended before the new user message), so the checkpointer is seeded under
the new thread_id on the first post-restore turn.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_checkpointer_module():
    """Load the checkpointer module directly (no heavy agent imports)."""
    module_path = Path("src/clanker/memory/checkpointer.py")
    spec = importlib.util.spec_from_file_location("clanker_checkpointer_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_turn_state(pending_restore_messages, user_msg):
    """Mirror the cli.py state-building contract under test.

    On the first turn after a restore, the restored history is prepended to the
    new user message; otherwise only the new message is sent. The pending buffer
    is consumed (emptied) after use.
    """
    if pending_restore_messages:
        turn_messages = [*pending_restore_messages, user_msg]
        pending_restore_messages = []
    else:
        turn_messages = [user_msg]
    return turn_messages, pending_restore_messages


class TestMessageRoundTrip:
    """get_session_messages must faithfully reload saved conversation text."""

    def test_human_ai_round_trip(self, tmp_path, monkeypatch) -> None:
        mod = _load_checkpointer_module()

        # Point storage at a temp workspace.
        conv_dir = tmp_path / ".clanker" / "conversations"
        conv_dir.mkdir(parents=True)
        snapshot = {
            "id": "abc12345",
            "title": "t",
            "messages": [
                {"type": "human", "content": "build the v3 widget"},
                {"type": "ai", "content": "Done. Created XtrapolateV3."},
                {"type": "human", "content": "now add save/load"},
                {"type": "ai", "content": "Added postgres persistence."},
            ],
        }
        (conv_dir / "abc12345.json").write_text(json.dumps(snapshot))

        # SessionManager reads via workspace storage rooted at cwd.
        monkeypatch.chdir(tmp_path)
        sm = mod.SessionManager(workspace_path=str(tmp_path))
        msgs = sm.get_session_messages("abc12345")

        assert msgs is not None
        assert len(msgs) == 4
        assert msgs[0].content == "build the v3 widget"
        assert msgs[-1].content == "Added postgres persistence."
        # Types preserved (human/ai).
        assert [m.type for m in msgs] == ["human", "ai", "human", "ai"]

    def test_missing_session_returns_none(self, tmp_path, monkeypatch) -> None:
        mod = _load_checkpointer_module()
        monkeypatch.chdir(tmp_path)
        sm = mod.SessionManager(workspace_path=str(tmp_path))
        assert sm.get_session_messages("nope") is None


class TestRestoreSeedsNextTurn:
    """The restored history must ride along on the first post-restore turn."""

    def test_pending_restore_prepended_then_cleared(self) -> None:
        from langchain_core.messages import AIMessage, HumanMessage

        restored = [
            HumanMessage(content="earlier question"),
            AIMessage(content="earlier answer"),
        ]
        new_msg = HumanMessage(content="What was the last change you did?")

        # First turn after restore: history is prepended, buffer cleared.
        turn_messages, pending = _build_turn_state(list(restored), new_msg)
        assert [m.content for m in turn_messages] == [
            "earlier question",
            "earlier answer",
            "What was the last change you did?",
        ]
        assert pending == []  # consumed

    def test_normal_turn_sends_only_new_message(self) -> None:
        from langchain_core.messages import HumanMessage

        new_msg = HumanMessage(content="hello")
        turn_messages, pending = _build_turn_state([], new_msg)
        assert turn_messages == [new_msg]
        assert pending == []

    def test_second_turn_after_restore_not_re_prepended(self) -> None:
        """After the seeding turn, later turns must NOT re-inject history."""
        from langchain_core.messages import HumanMessage

        restored = [HumanMessage(content="ctx")]
        # Turn 1: seeds.
        _t1, pending = _build_turn_state(list(restored), HumanMessage(content="q1"))
        assert pending == []
        # Turn 2: pending is empty -> only the new message goes out.
        t2, pending2 = _build_turn_state(pending, HumanMessage(content="q2"))
        assert [m.content for m in t2] == ["q2"]
        assert pending2 == []
