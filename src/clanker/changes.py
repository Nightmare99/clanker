"""Session edit journal. Undo refuses files changed outside the recorded edit chain."""

from __future__ import annotations

import difflib
import hashlib
import os
import tempfile
import threading
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path


class ChangeConflictError(ValueError):
    """The file no longer matches the version the agent read or wrote."""


@dataclass
class Change:
    id: int
    path: Path
    before: bytes | None
    after: bytes | None
    turn: int
    actor: str
    undone: bool = False

    def diff(self) -> str:
        before = (self.before or b"").decode("utf-8", errors="replace")
        after = (self.after or b"").decode("utf-8", errors="replace")
        lines = difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=str(self.path) if self.before is not None else "/dev/null",
            tofile=str(self.path) if self.after is not None else "/dev/null",
        )
        return "".join(
            line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
            for line in lines
        )


def _contents(path: Path) -> bytes | None:
    if path.is_symlink():
        raise ChangeConflictError(f"Path is now a symlink: {path}")
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _replace(path: Path, content: bytes | None) -> None:
    if content is None:
        path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, temporary = tempfile.mkstemp(prefix=".clanker-edit-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ChangeJournal:
    def __init__(self) -> None:
        self.changes: list[Change] = []
        self.turn = 0
        self.revision = 0
        self._reads: dict[tuple[str, Path], bytes | None] = {}
        self._lock = threading.RLock()

    def begin_turn(self) -> int:
        with self._lock:
            self.turn += 1
            return self.turn

    def observe(self, path: Path, content: bytes | None) -> None:
        with self._lock:
            self._reads[(change_actor.get(), path)] = self._digest(content)

    @staticmethod
    def _digest(content: bytes | None) -> bytes | None:
        return hashlib.sha256(content).digest() if content is not None else None

    def write(
        self, path: Path, content: bytes, *, append: bool = False, expected: bytes | None = None
    ) -> Change | None:
        from clanker.execution import check_cancelled

        with self._lock:
            check_cancelled()
            if path.resolve() != path:
                raise ChangeConflictError(f"Path changed through a symlink: {path}")
            before = _contents(path)
            key = (change_actor.get(), path)
            if key in self._reads and self._reads[key] != self._digest(before):
                raise ChangeConflictError(
                    f"File changed since your last read; read it again: {path}"
                )
            if expected is not None and before != expected:
                raise ChangeConflictError(f"File changed while preparing the edit: {path}")
            after = (before or b"") + content if append else content
            if before == after:
                return None
            _replace(path, after)
            change = Change(
                len(self.changes) + 1,
                path,
                before,
                after,
                change_turn.get() or self.turn,
                change_actor.get(),
            )
            self.changes.append(change)
            self._reads[key] = self._digest(after)
            self.revision += 1
            return change

    def snapshot(self) -> list[Change]:
        with self._lock:
            return list(self.changes)

    def undo(self, ids: list[int]) -> int:
        """Preflight every file before undoing any edits, newest first.

        External edits and newer agent edits are conflicts. No git reset or
        checkout is used, so staged and pre-existing user changes are preserved.
        """
        with self._lock:
            selected = [c for c in reversed(self.changes) if c.id in ids and not c.undone]
            targets: dict[Path, bytes | None] = {}
            originals: dict[Path, bytes | None] = {}
            for change in selected:
                path = change.path
                if path.resolve() != path:
                    raise ChangeConflictError(f"Path changed through a symlink: {path}")
                if path not in targets:
                    targets[path] = originals[path] = _contents(path)
                if targets[path] != change.after:
                    raise ChangeConflictError(f"Undo would overwrite newer changes: {path}")
                targets[path] = change.before
            written: list[Path] = []
            try:
                for path, content in targets.items():
                    if _contents(path) != originals[path]:
                        raise ChangeConflictError(f"File changed during undo: {path}")
                    _replace(path, content)
                    written.append(path)
            except (OSError, ChangeConflictError):
                for path in reversed(written):
                    if _contents(path) == targets[path]:
                        _replace(path, originals[path])
                raise
            for change in selected:
                change.undone = True
            if selected:
                self.revision += 1
            return len(selected)


active_journal: ContextVar[ChangeJournal | None] = ContextVar("change_journal", default=None)
change_actor: ContextVar[str] = ContextVar("change_actor", default="main")
change_turn: ContextVar[int] = ContextVar("change_turn", default=0)
