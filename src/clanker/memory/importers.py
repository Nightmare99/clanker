"""Read local coding-agent conversations without importing tool or system state."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import yaml
from langchain_core.messages import AIMessage, HumanMessage

SOURCES = ("Codex", "Claude Code", "OpenCode", "GitHub Copilot")


@dataclass(frozen=True)
class ImportCandidate:
    source: str
    session_id: str
    title: str
    updated_at: str
    path: Path
    cwd: str = ""


def _timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            block if isinstance(block, str) else block.get("text", "")
            for block in value
            if isinstance(block, str) or (isinstance(block, dict) and block.get("type") in ("text", "input_text", "output_text"))
        )
    if isinstance(value, dict):
        return _text(value.get("content") or value.get("text"))
    return ""


def _title(value: str, fallback: str) -> str:
    return " ".join(value.split())[:90] or fallback


def _real_prompt(value: str) -> bool:
    """Ignore harness-injected Codex setup records when finding user turns."""
    prompt = value.lstrip().casefold()
    return bool(prompt) and not prompt.startswith((
        "# agents.md instructions for ",
        "<environment_context>",
        "<command-name>",
        "<command-message>",
        "<instructions>",
    ))


def _in_workspace(candidate_cwd: str, workspace: Path) -> bool:
    if not candidate_cwd:
        return False
    try:
        Path(candidate_cwd).expanduser().resolve().relative_to(workspace)
        return True
    except (OSError, ValueError):
        return False


def _workspace_from_record(record: object) -> str:
    if not isinstance(record, dict):
        return ""
    for key in ("cwd", "workingDirectory", "workspacePath", "workspaceRoot"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    for key in ("workspace", "data", "payload"):
        value = _workspace_from_record(record.get(key))
        if value:
            return value
    return ""


def _copilot_workspace(path: Path) -> str:
    metadata = path.with_name("workspace.yaml")
    try:
        with metadata.open(encoding="utf-8") as stream:
            return _workspace_from_record(yaml.safe_load(stream))
    except (OSError, yaml.YAMLError):
        return ""


def _json_lines(path: Path):
    with path.open(encoding="utf-8-sig", errors="replace") as stream:
        for line in stream:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                yield item


def _file_candidate(source: str, path: Path) -> ImportCandidate | None:
    first_user = ""
    event_user = ""
    session_id = path.stem.removeprefix("rollout-")
    cwd = _copilot_workspace(path) if source == "GitHub Copilot" else ""
    try:
        # A bounded preview avoids loading an entire transcript for every row.
        with path.open(encoding="utf-8-sig", errors="replace") as stream:
            for index, line in enumerate(stream):
                if index >= 500:
                    break
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if source == "Codex":
                    payload = item.get("payload") or {}
                    if item.get("type") == "session_meta":
                        session_id = payload.get("id") or session_id
                        cwd = payload.get("cwd") or cwd
                    elif item.get("type") == "turn_context":
                        cwd = payload.get("cwd") or cwd
                    elif item.get("type") == "response_item" and payload.get("role") == "user":
                        text = _text(payload.get("content"))
                        if not first_user and _real_prompt(text):
                            first_user = text
                    elif item.get("type") == "event_msg" and payload.get("type") == "user_message":
                        text = _text(payload.get("message"))
                        if not event_user and _real_prompt(text):
                            event_user = text
                elif source == "Claude Code":
                    session_id = item.get("sessionId") or session_id
                    cwd = item.get("cwd") or cwd
                    if item.get("type") == "user" and not item.get("isSidechain"):
                        content = (item.get("message") or {}).get("content")
                        if not (isinstance(content, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in content)):
                            first_user = _text(content)
                else:
                    event_type = item.get("type") or item.get("event")
                    cwd = _workspace_from_record(item) or cwd
                    if event_type in ("user.message", "user_message"):
                        first_user = _copilot_text(item)
                if first_user and cwd:
                    break
        first_user = first_user or event_user
        if not first_user:
            return None
        return ImportCandidate(source, str(session_id), _title(first_user, path.stem), _timestamp(path), path, cwd)
    except OSError:
        return None


def _copilot_text(item: dict) -> str:
    data = item.get("data") or item.get("payload") or item
    if isinstance(data, dict):
        message = data.get("message") or data.get("content") or data.get("text")
        return _text(message)
    return _text(data)


def _opencode_db() -> Path:
    data_root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return data_root / "opencode" / "opencode.db"


def _connect_db(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True)


def _opencode_has_user_prompt(connection: sqlite3.Connection, session_id: str) -> bool:
    rows = connection.execute(
        "SELECT m.data, p.data FROM message m JOIN part p ON p.message_id = m.id "
        "WHERE m.session_id = ?",
        (session_id,),
    )
    for raw_message, raw_part in rows:
        message = json.loads(raw_message)
        part = json.loads(raw_part)
        if (message.get("role") == "user" and part.get("type") == "text"
                and not part.get("synthetic") and str(part.get("text") or "").strip()):
            return True
    return False


def discover(source: str, cwd: str | Path | None = None) -> list[ImportCandidate]:
    """List source sessions under the current workspace, newest first."""
    if source not in SOURCES:
        raise ValueError(f"Unsupported source: {source}")
    workspace = Path(cwd or Path.cwd()).expanduser().resolve()
    if source == "OpenCode":
        db = _opencode_db()
        if not db.is_file():
            return []
        try:
            with closing(_connect_db(db)) as connection:
                rows = connection.execute(
                    "SELECT id, title, time_updated, directory FROM session WHERE parent_id IS NULL ORDER BY time_updated DESC"
                ).fetchall()
                return [
                    ImportCandidate(source, sid, _title(title or "", sid),
                                    datetime.fromtimestamp((updated or 0) / 1000).astimezone().isoformat(timespec="seconds"),
                                    db, directory or "")
                    for sid, title, updated, directory in rows
                    if _in_workspace(directory or "", workspace)
                    and _opencode_has_user_prompt(connection, sid)
                ]
        except (OSError, sqlite3.Error, ValueError):
            return []

    if source == "Codex":
        root = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        paths = list((root / "sessions").glob("**/rollout-*.jsonl"))
        paths.extend((root / "archived_sessions").glob("rollout-*.jsonl"))
    elif source == "Claude Code":
        root = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
        paths = [p for p in (root / "projects").glob("*/*.jsonl") if "subagents" not in p.parts]
    else:
        root = Path(os.environ.get("COPILOT_HOME", str(Path.home() / ".copilot")))
        paths = list((root / "session-state").glob("*/events.jsonl"))
    paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        candidate for path in paths
        if (candidate := _file_candidate(source, path))
        and _in_workspace(candidate.cwd, workspace)
    ]


def _pair(role: str, text: str):
    if not text.strip():
        return None
    return HumanMessage(content=text) if role == "user" else AIMessage(content=text)


def _parse_codex(path: Path) -> list:
    response_roles = {
        item.get("payload", {}).get("role")
        for item in _json_lines(path)
        if item.get("type") == "response_item"
        and item.get("payload", {}).get("type") == "message"
        and item.get("payload", {}).get("role") in ("user", "assistant")
        and (item.get("payload", {}).get("role") != "user"
             or _real_prompt(_text(item.get("payload", {}).get("content"))))
    }
    messages = []
    for item in _json_lines(path):
        payload = item.get("payload") or {}
        if item.get("type") == "response_item" and payload.get("type") == "message":
            role = payload.get("role")
            content = _text(payload.get("content"))
        elif item.get("type") == "event_msg":
            role = {"user_message": "user", "agent_message": "assistant"}.get(payload.get("type"))
            if role in response_roles:
                continue
            content = _text(payload.get("message"))
        else:
            continue
        if role == "user" and not _real_prompt(content):
            continue
        if role in ("user", "assistant") and (message := _pair(role, content)):
            messages.append(message)
    return messages


def _parse_claude(path: Path) -> list:
    messages = []
    seen: set[str] = set()
    for item in _json_lines(path):
        role = item.get("type")
        if role not in ("user", "assistant") or item.get("isSidechain"):
            continue
        content = (item.get("message") or {}).get("content")
        if isinstance(content, list) and any(
            isinstance(block, dict) and block.get("type") in ("tool_use", "tool_result")
            for block in content
        ):
            # Keep human prose alongside a tool block if present, but never
            # import the tool payload itself.
            content = [block for block in content if isinstance(block, dict) and block.get("type") == "text"]
        text = _text(content)
        identity = item.get("uuid") or f"{role}:{item.get('message', {}).get('id', '')}:{text}"
        if identity in seen:
            continue
        seen.add(identity)
        if message := _pair(role, text):
            messages.append(message)
    return messages


def _parse_copilot(path: Path) -> list:
    messages = []
    for item in _json_lines(path):
        kind = item.get("type") or item.get("event")
        role = {"user.message": "user", "assistant.message": "assistant"}.get(kind)
        if role and (message := _pair(role, _copilot_text(item))):
            messages.append(message)
    return messages


def _parse_opencode(candidate: ImportCandidate) -> list:
    with closing(_connect_db(candidate.path)) as connection:
        rows = connection.execute(
            "SELECT m.id, m.data, p.data FROM message m "
            "LEFT JOIN part p ON p.message_id = m.id "
            "WHERE m.session_id = ? ORDER BY m.time_created, m.id, p.time_created, p.id",
            (candidate.session_id,),
        ).fetchall()
    grouped: dict[str, tuple[str, list[str]]] = {}
    for message_id, raw_info, raw_part in rows:
        info = json.loads(raw_info)
        role = info.get("role")
        if role not in ("user", "assistant"):
            continue
        if message_id not in grouped:
            grouped[message_id] = (role, [])
        if raw_part:
            part = json.loads(raw_part)
            if part.get("type") == "text" and not part.get("synthetic"):
                grouped[message_id][1].append(part.get("text", ""))
    return [message for role, parts in grouped.values() if (message := _pair(role, "\n".join(parts)))]


def load(candidate: ImportCandidate) -> list:
    """Convert a selected session to plain human and assistant messages."""
    if candidate.source == "Codex":
        messages = _parse_codex(candidate.path)
    elif candidate.source == "Claude Code":
        messages = _parse_claude(candidate.path)
    elif candidate.source == "OpenCode":
        messages = _parse_opencode(candidate)
    elif candidate.source == "GitHub Copilot":
        messages = _parse_copilot(candidate.path)
    else:
        raise ValueError(f"Unsupported source: {candidate.source}")
    if not any(isinstance(message, HumanMessage) for message in messages):
        raise ValueError("This session has no user messages that Clanker can import.")
    return messages
