# Memory

Clanker keeps durable facts across conversations: project conventions,
preferences, decisions, and verified fixes. Workspace memories belong to the
current project. You can explicitly choose `global` for a preference that
should apply across projects. Conversation history and active task state remain
separate from this long-term knowledge.

## How it works

1. `remember` stores a fact, preference, decision, or episode. Exact duplicates
   reuse the existing record. Credential-shaped values are rejected. Inferred
   memories are marked `auto`, distinct from user-stated guidance.
2. Each turn retrieves relevant active memories. Search uses a disposable
   SQLite FTS5 index plus keyword and tag ranking; prompt injection has a token
   budget. `recall` lets the agent look up more. If FTS5 is unavailable in the
   Python build, keyword search remains available.
3. `revise_memory` supersedes an outdated record while retaining its stale
   predecessor for review. A memory citing a repository file is withheld from
   retrieval if that file changes until the memory is verified again.
4. `/memories` opens a searchable TUI panel. You can inspect provenance and
   match reasons, edit content and tags, pin, verify, mark stale, or delete.

Memories are context to check against the repository, not instructions that
override the user or project files. Imported conversations remain transcripts;
their contents are not automatically promoted into durable memory.

## Storage and migration

The Markdown files remain authoritative. Workspace files live at
`.clanker/memories/<id>.md`; explicitly global files live at
`~/.clanker/memories/<id>.md`. The SQLite index at
`.clanker/memory-index.sqlite` can be deleted and rebuilt from the files.
Existing Markdown files load without being rewritten.

Each memory has a type (`fact`, `preference`, `decision`, or `episode`), scope,
source (`user`, `auto`, or `system`), tags, timestamps, status, optional
evidence, and optional metadata. New files use YAML frontmatter:

```markdown
---
id: a1b2c3d4
source: user
created: '2026-08-21T10:15:00+00:00'
updated: '2026-08-21T10:15:00+00:00'
kind: fact
scope: workspace
pinned: false
status: active
tags:
- convention
verified: null
evidence: pyproject.toml
metadata: {}
---

This project uses pytest with asyncio_mode=auto.
```

Writes are atomic. When evidence names an existing repository file, Clanker
records its modification time; a later change makes the memory require
re-verification. A conversation ID or URL may also be recorded as evidence,
but only repository files receive automatic change detection.

## Tools and controls

| Tool | Purpose |
|------|---------|
| `remember(content, tags, auto, kind, scope, evidence)` | Save durable knowledge; workspace scope is the default |
| `recall(query, tags, n_results)` | Search active memories |
| `revise_memory(memory_id, replacement, evidence)` | Replace an outdated fact while keeping its history |
| `forget(memory_id)` | Delete a memory |
| `list_memories(limit)` | Inspect stored entries |

Use `/remember <text>` for a quick workspace memory, **F6** or `/memories` to browse and
edit in the TUI, and `/forget <id>` to delete by ID. In `--no-tui` mode,
`/memories` prints a text list. The TUI's **Add** form can select `global`
scope; the agent's `remember` tool can do the same when explicitly appropriate.

Subagents can read memories from their parent's workspace even when they use a
Git worktree. They cannot change long-term memories; the parent session
curates writes.

Memory tools and automatic injection can be disabled with `tools.memory: false`
in `~/.clanker/config.yaml`. See [Configuration](configuration.md#tool-feature-flags).

## Retrieval evaluation

From a development checkout, run `python scripts/eval_memory.py`. The bundled
synthetic fixture measures recall, precision, stale-memory leakage, latency,
and estimated injected tokens. The evaluator creates a temporary workspace and
never reads live memory files. Add representative cases to
`tests/fixtures/memory_eval.json` before tuning search.

Memory management is separate from conversation compaction and `/resume`.
Compaction handles the current context window; `/resume` loads a saved
conversation; long-term memory carries selected knowledge across sessions.
