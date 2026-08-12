"""Regression coverage: /restore must update conversation_messages in place.

Prior bug: ``_handle_slash_command``'s restore branch reassigned the local
``conversation_messages`` variable (``conversation_messages = list(messages)``)
instead of mutating the list object shared with ``self._conversation_messages``.
Since that's the same list ``_run_agent`` keeps appending to and saving
snapshots from -- and now what the F3 history modal reads directly -- the
restored history silently never stuck: it only rode along on the very next
turn's graph state via ``_pending_restore_messages``, then vanished from
everything else that tracked "the conversation so far".
"""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage

from clanker.ui.app import ClankerApp


def _make_app(monkeypatch, restored_messages: list | None) -> ClankerApp:
    app = ClankerApp.__new__(ClankerApp)
    app.clanker_console = MagicMock()
    app._session_manager = MagicMock()
    app._session_manager.get_session_messages.return_value = restored_messages
    app._conversation_messages = [
        HumanMessage(content="old question"),
        AIMessage(content="old answer"),
    ]
    app._pending_restore_messages = []
    app.get_chat_log = MagicMock(return_value=MagicMock())

    monkeypatch.setattr("clanker.cli.handle_command", lambda *a, **k: "restore:session123")

    return app


def test_restore_mutates_conversation_messages_in_place(monkeypatch) -> None:
    restored = [HumanMessage(content="earlier q"), AIMessage(content="earlier a")]
    app = _make_app(monkeypatch, restored)
    original_list = app._conversation_messages

    result = app._handle_slash_command("/restore session123")

    assert result == "skip"
    # Same object, mutated in place -- not rebound to a disconnected new list.
    assert app._conversation_messages is original_list
    assert [m.content for m in app._conversation_messages] == ["earlier q", "earlier a"]
    assert [m.content for m in app._pending_restore_messages] == ["earlier q", "earlier a"]


def test_restore_saves_previous_conversation_before_switching(monkeypatch) -> None:
    app = _make_app(monkeypatch, [HumanMessage(content="earlier q")])
    # save_conversation_snapshot is handed the SAME list object that gets
    # mutated in place right after -- capture a copy at call-time, since
    # inspecting call_args afterwards would see the post-restore content.
    saved_snapshots: list[list] = []
    app._session_manager.save_conversation_snapshot.side_effect = (
        lambda msgs: saved_snapshots.append(list(msgs))
    )

    app._handle_slash_command("/restore session123")

    assert len(saved_snapshots) == 1
    assert [m.content for m in saved_snapshots[0]] == ["old question", "old answer"]


def test_restore_missing_session_leaves_conversation_messages_untouched(monkeypatch) -> None:
    app = _make_app(monkeypatch, None)
    original_list = app._conversation_messages

    result = app._handle_slash_command("/restore ghost")

    assert result == "skip"
    assert app._conversation_messages is original_list
    assert [m.content for m in app._conversation_messages] == ["old question", "old answer"]
    app.get_chat_log.return_value.add_message.assert_called_once()
