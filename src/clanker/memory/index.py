"""Disposable SQLite FTS5 index for Markdown memories.

Markdown remains authoritative. The index can be deleted or rebuilt at any time.
Systems whose Python SQLite lacks FTS5 use the store's lexical search instead.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path


def fts5_available() -> bool:
    """Probe the SQLite library bundled with this Python executable."""
    try:
        with sqlite3.connect(":memory:") as connection:
            connection.execute("CREATE VIRTUAL TABLE memory_probe USING fts5(content)")
        return True
    except sqlite3.Error:
        return False


class MemoryIndex:
    """Keep an FTS5 lookup table in sync with a set of source files."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def search(self, query: str, documents: list[tuple[str, Path, str, str]]) -> dict[str, float] | None:
        """Return ID-to-rank for matching documents, or None without FTS5.

        Each document is (id, Markdown path, content, searchable tags). File
        mtimes detect hand edits; the index is rebuilt if its schema is stale.
        """
        terms = re.findall(r"\w+", query, flags=re.UNICODE)
        if not terms:
            return {}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path, timeout=2) as connection:
                connection.execute("CREATE TABLE IF NOT EXISTS files (id TEXT PRIMARY KEY, path TEXT, mtime_ns INTEGER)")
                connection.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(id UNINDEXED, content, tags)"
                )
                known = {
                    row[0]: (row[1], row[2])
                    for row in connection.execute("SELECT id, path, mtime_ns FROM files")
                }
                current = set()
                for memory_id, path, content, tags in documents:
                    current.add(memory_id)
                    mtime = path.stat().st_mtime_ns
                    if known.get(memory_id) == (str(path), mtime):
                        continue
                    connection.execute("DELETE FROM memory_fts WHERE id = ?", (memory_id,))
                    connection.execute(
                        "INSERT INTO memory_fts (id, content, tags) VALUES (?, ?, ?)",
                        (memory_id, content, tags),
                    )
                    connection.execute(
                        "INSERT OR REPLACE INTO files (id, path, mtime_ns) VALUES (?, ?, ?)",
                        (memory_id, str(path), mtime),
                    )
                for missing in known.keys() - current:
                    connection.execute("DELETE FROM memory_fts WHERE id = ?", (missing,))
                    connection.execute("DELETE FROM files WHERE id = ?", (missing,))

                # Quoted terms prevent user input from becoming FTS query syntax.
                expression = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
                return {
                    row[0]: -float(row[1])
                    for row in connection.execute(
                        "SELECT id, bm25(memory_fts) FROM memory_fts WHERE memory_fts MATCH ?",
                        (expression,),
                    )
                }
        except (OSError, sqlite3.Error):
            return None
