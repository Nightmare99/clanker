"""External transcripts become ordinary Clanker sessions through the wizard."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, HumanMessage
from textual.widgets import Input

from clanker.memory.checkpointer import SessionManager
from clanker.memory.importers import discover, load
from clanker.ui.app import ClankerApp
from clanker.ui.console import Console
from clanker.ui.conversation_picker import ConversationPickerScreen, ImportWizardScreen


def _jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path


def test_codex_import_discards_tool_calls_and_duplicate_event_messages(tmp_path, monkeypatch):
    root = tmp_path / "codex"
    _jsonl(root / "sessions" / "2026" / "09" / "27" / "rollout-test.jsonl", [
        {"type": "session_meta", "payload": {"id": "codex-1", "cwd": "/repo"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "duplicate"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Fix bug"}]}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "execute_shell", "arguments": "private command"}},
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "duplicate"}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Fixed it"}]}},
    ])
    monkeypatch.setenv("CODEX_HOME", str(root))
    candidates = discover("Codex", "/repo")
    assert len(candidates) == 1
    assert candidates[0].session_id == "codex-1"
    assert candidates[0].cwd == "/repo"
    assert [(type(m), m.content) for m in load(candidates[0])] == [
        (HumanMessage, "Fix bug"), (AIMessage, "Fixed it")
    ]


def test_codex_picker_shows_only_workspace_sessions_with_real_prompts(tmp_path, monkeypatch):
    root = tmp_path / "codex"
    sessions = root / "sessions" / "2026" / "09" / "27"
    _jsonl(sessions / "rollout-current.jsonl", [
        {"type": "session_meta", "payload": {"id": "current", "cwd": "/repo"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "# AGENTS.md instructions for /repo\n<INSTRUCTIONS>setup</INSTRUCTIONS>"}
        ]}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "<environment_context><cwd>/repo</cwd></environment_context>"}
        ]}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "<command-name>/add-dir</command-name>"}
        ]}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "Fix the picker"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "Fix the picker"}
        ]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": "Done"}
        ]}},
    ])
    _jsonl(sessions / "rollout-other.jsonl", [
        {"type": "session_meta", "payload": {"id": "other", "cwd": "/another-repo"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "A real but unrelated task"}
        ]}},
    ])
    _jsonl(sessions / "rollout-setup-only.jsonl", [
        {"type": "session_meta", "payload": {"id": "setup-only", "cwd": "/repo"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "<environment_context>setup</environment_context>"}
        ]}},
    ])
    monkeypatch.setenv("CODEX_HOME", str(root))

    candidate, = discover("Codex", "/repo")
    assert candidate.session_id == "current"
    assert candidate.title == "Fix the picker"
    assert [message.content for message in load(candidate)] == ["Fix the picker", "Done"]
    assert discover("Codex", "/repo/subdirectory") == []


def test_codex_event_message_is_used_when_response_items_only_contain_setup(tmp_path, monkeypatch):
    root = tmp_path / "codex"
    _jsonl(root / "sessions" / "rollout-event.jsonl", [
        {"type": "session_meta", "payload": {"id": "event", "cwd": "/repo"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "<environment_context>setup</environment_context>"}
        ]}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "Actual question"}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": "Answer"}
        ]}},
    ])
    monkeypatch.setenv("CODEX_HOME", str(root))
    candidate, = discover("Codex", "/repo")
    assert candidate.title == "Actual question"
    assert [message.content for message in load(candidate)] == ["Actual question", "Answer"]


def test_claude_import_skips_tool_results_and_sidechains(tmp_path, monkeypatch):
    root = tmp_path / "claude"
    _jsonl(root / "projects" / "-repo" / "session.jsonl", [
        {"type": "user", "sessionId": "claude-1", "uuid": "u1", "cwd": "/repo",
         "message": {"role": "user", "content": "Review this"}},
        {"type": "user", "uuid": "tool", "message": {"role": "user", "content": [{"type": "tool_result", "content": "secret tool output"}]}},
        {"type": "assistant", "uuid": "side", "isSidechain": True,
         "message": {"content": [{"type": "text", "text": "subagent output"}]}},
        {"type": "assistant", "uuid": "a1", "message": {"content": [
            {"type": "thinking", "thinking": "private reasoning"},
            {"type": "text", "text": "Looks good"},
            {"type": "tool_use", "input": {"secret": "private"}},
        ]}},
        {"type": "assistant", "uuid": "a1", "message": {"content": [{"type": "text", "text": "Looks good"}]}},
    ])
    _jsonl(root / "projects" / "-other" / "session.jsonl", [
        {"type": "user", "sessionId": "claude-other", "cwd": "/other-repo",
         "message": {"role": "user", "content": "Unrelated task"}},
    ])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(root))
    candidate, = discover("Claude Code", "/repo")
    assert candidate.session_id == "claude-1"
    assert [m.content for m in load(candidate)] == ["Review this", "Looks good"]


def test_copilot_cli_import_uses_only_conversation_events(tmp_path, monkeypatch):
    root = tmp_path / "copilot"
    _jsonl(root / "session-state" / "copilot-1" / "events.jsonl", [
        {"type": "session.start", "data": {"cwd": "/repo"}},
        {"type": "user.message", "data": {"message": {"content": "What changed?"}}},
        {"type": "tool.execution_complete", "data": {"message": "secret tool output"}},
        {"type": "assistant.message", "data": {"content": "Two files changed."}},
    ])
    _jsonl(root / "session-state" / "copilot-other" / "events.jsonl", [
        {"type": "session.start", "data": {"cwd": "/other-repo"}},
        {"type": "user.message", "data": {"message": {"content": "Unrelated task"}}},
    ])
    _jsonl(root / "session-state" / "copilot-unknown" / "events.jsonl", [
        {"type": "user.message", "data": {"message": {"content": "Unknown workspace"}}},
    ])
    monkeypatch.setenv("COPILOT_HOME", str(root))
    candidate, = discover("GitHub Copilot", "/repo")
    assert [m.content for m in load(candidate)] == ["What changed?", "Two files changed."]


def test_opencode_readonly_sqlite_import(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    db = data_root / "opencode" / "opencode.db"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as connection:
        connection.executescript("""
            CREATE TABLE session (id TEXT, title TEXT, time_updated INTEGER, directory TEXT, parent_id TEXT);
            CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, data TEXT);
            CREATE TABLE part (id TEXT, message_id TEXT, time_created INTEGER, data TEXT);
        """)
        connection.execute("INSERT INTO session VALUES (?, ?, ?, ?, NULL)", ("ses1", "OpenCode task", 1760000000000, "/repo"))
        connection.execute("INSERT INTO session VALUES (?, ?, ?, ?, NULL)", ("ses2", "Other task", 1760000000001, "/other-repo"))
        connection.execute("INSERT INTO session VALUES (?, ?, ?, ?, NULL)", ("ses3", "Empty task", 1760000000002, "/repo"))
        connection.executemany("INSERT INTO message VALUES (?, ?, ?, ?)", [
            ("m1", "ses1", 1, json.dumps({"role": "user"})),
            ("m2", "ses1", 2, json.dumps({"role": "assistant"})),
        ])
        connection.executemany("INSERT INTO part VALUES (?, ?, ?, ?)", [
            ("p1", "m1", 1, json.dumps({"type": "text", "text": "Build feature"})),
            ("p2", "m2", 1, json.dumps({"type": "tool", "state": {"output": "secret"}})),
            ("p3", "m2", 2, json.dumps({"type": "text", "text": "Done"})),
        ])
    monkeypatch.setenv("XDG_DATA_HOME", str(data_root))
    candidate, = discover("OpenCode", "/repo")
    assert [m.content for m in load(candidate)] == ["Build feature", "Done"]
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 3


def test_restore_resume_commands_and_session_sort(tmp_path):
    from clanker.cli import handle_command

    manager = SessionManager(workspace_path=str(tmp_path))
    console = MagicMock()
    assert handle_command("/restore", console, manager, []) == "restore_picker"
    assert handle_command("/resume", console, manager, []) == "restore_picker"
    assert handle_command("/restore abc123", console, manager, []) == "restore:abc123"
    assert handle_command("/resume abc123", console, manager, []) == "restore:abc123"
    assert handle_command("/import", console, manager, []) == "import_wizard"

    directory = tmp_path / ".clanker" / "conversations"
    directory.mkdir(parents=True)
    for session_id, updated_at in (("new", "2026-09-27T10:00:00"), ("old", "2026-01-01T00:00:00")):
        (directory / f"{session_id}.meta.json").write_text(json.dumps({
            "id": session_id, "title": session_id, "updated_at": updated_at,
        }))
        (directory / f"{session_id}.json").write_text(json.dumps({"message_count": 1}))
    assert [session["id"] for session in manager.list_sessions()] == ["new", "old"]


async def test_restore_picker_sorts_pages_and_preserves_state_on_cancel(tmp_path):
    app = ClankerApp(Console())
    app._play_hero = AsyncMock()
    app._session_manager = SessionManager(workspace_path=str(tmp_path))
    app._conversation_messages = [HumanMessage(content="Current draft")]
    app._pending_restore_messages = []
    sessions = [
        {"id": f"s{i}", "title": f"Chat {i}", "updated_at": f"2026-09-{i + 1:02d}T00:00:00", "message_count": i}
        for i in range(24)
    ]
    async with app.run_test(size=(100, 30)) as pilot:
        app.push_screen(ConversationPickerScreen(sessions))
        await pilot.pause()
        picker = app.screen
        assert picker._filtered[0][2] == "s23"
        await pilot.press("pagedown")
        assert picker._page == 1
        await pilot.press("escape")
        assert app._conversation_messages[0].content == "Current draft"


async def test_restore_picker_search_enter_selects_filtered_session():
    app = ClankerApp(Console())
    app._play_hero = AsyncMock()
    selected: list[str] = []
    async with app.run_test(size=(100, 30)) as pilot:
        app.push_screen(ConversationPickerScreen([
            {"id": "old", "title": "Old task", "updated_at": "2026-01-01"},
            {"id": "new", "title": "New task", "updated_at": "2026-09-27"},
        ]), selected.append)
        await pilot.pause()
        picker = app.screen
        search = picker.query_one("#picker-search", Input)
        search.focus()
        search.value = "Old task"
        await pilot.pause()
        assert len(picker._filtered) == 1
        await pilot.press("enter")
        await pilot.pause()
        assert selected == ["old"]


async def test_import_wizard_confirmation_creates_resumable_session(tmp_path, monkeypatch):
    root = tmp_path / "codex"
    _jsonl(root / "sessions" / "2026" / "09" / "27" / "rollout-example.jsonl", [
        {"type": "session_meta", "payload": {"id": "external-1", "cwd": str(tmp_path)}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Do the work"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Done"}]}},
    ])
    monkeypatch.setenv("CODEX_HOME", str(root))
    app = ClankerApp(Console())
    app._play_hero = AsyncMock()
    app._session_manager = SessionManager(workspace_path=str(tmp_path))
    app._conversation_messages = [HumanMessage(content="Old chat")]
    app._pending_restore_messages = []
    async with app.run_test(size=(100, 30)) as pilot:
        app._handle_slash_command("/import")
        await pilot.pause()
        wizard = app.screen
        assert isinstance(wizard, ImportWizardScreen)
        await pilot.press("enter")
        await pilot.pause()
        assert wizard._stage == "sessions"
        await pilot.press("enter")
        await pilot.pause()
        assert wizard._stage == "review"
        assert app._conversation_messages[0].content == "Old chat"
        await pilot.click("#wizard-import")
        await pilot.pause()
        assert [m.content for m in app._conversation_messages] == ["Do the work", "Done"]
        assert [m.content for m in app._pending_restore_messages] == ["Do the work", "Done"]
        session_id = app._session_manager.session_id
        assert [m.content for m in app._session_manager.get_session_messages(session_id)] == ["Do the work", "Done"]
        assert any(s["id"] == session_id for s in app._session_manager.list_sessions())


async def test_import_cancel_closes_modal_once_without_changing_session(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex"))
    app = ClankerApp(Console())
    app._play_hero = AsyncMock()
    app._session_manager = SessionManager(workspace_path=str(tmp_path))
    app._conversation_messages = [HumanMessage(content="Current chat")]
    app._pending_restore_messages = []
    async with app.run_test(size=(100, 30)) as pilot:
        app._handle_slash_command("/import")
        await pilot.pause()
        wizard = app.screen
        await pilot.press("enter")
        await pilot.pause()
        assert wizard._stage == "sessions"
        await pilot.click("#picker-cancel")
        await pilot.pause()
        assert app.screen is not wizard
        wizard.action_cancel()  # A late second event must not pop the app's base screen.
        assert [message.content for message in app._conversation_messages] == ["Current chat"]
