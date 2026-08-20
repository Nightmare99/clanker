# Memory

Memory lets the agent persist facts across conversations — project
conventions, your preferences, config details, recurring issues and their
fixes — so it doesn't have to relearn them every session. It's workspace
memory: stored per-project, not shared globally.

This is a different thing from context compaction (the `context:` block in
[General Settings](configuration.md#general-settings), which automatically
summarizes a long conversation to stay within the model's context window) and
from the `memory:` block in that same settings file (which only controls
session/conversation persistence, not knowledge storage). Memory, here, is the
agent's own longer-term knowledge store, independent of any one conversation.

## How it works

1. **Proactive storage**: the agent is instructed to call `remember`
   on its own — without being asked — whenever it notices something worth
   keeping: a convention, a preference, a config detail, a fix to a recurring
   problem, a decision the user stated.
2. **Automatic injection**: at the start of a conversation, a handful of
   relevant memories are pulled into the system prompt automatically —
   matched against your first message when possible, or the most recent
   memories otherwise. The agent doesn't need to call `recall` just to see
   what it already knows.
3. **On-demand retrieval**: `recall` is for digging up something more
   specific than what showed up unprompted, by keyword and/or tag.

## Storage

Memories are stored as individual markdown files with YAML frontmatter,
under `.clanker/memories/` in the current workspace:

```
.clanker/memories/
  a1b2c3d4.md
  e5f6a7b8.md
```

**`a1b2c3d4.md`**:

```markdown
---
id: a1b2c3d4
source: user
created: 2026-08-21T10:15:00
tags: [convention, testing]
---

This project uses pytest with asyncio_mode=auto (set in pyproject.toml).
Async test functions don't need @pytest.mark.asyncio.
```

`source` is `user` (explicitly requested), `auto` (the agent noticed and
stored it on its own), or `system`. There is no personal (`~`) memory store —
memory is always scoped to the current workspace.

## Tools

| Tool | Parameters | Description |
|------|------------|--------------|
| `remember` | `content`, `tags` | Store information for future sessions |
| `recall` | `query`, `tags`, `n_results` (default 5) | Retrieve relevant memories by keyword and/or tag |
| `forget` | `memory_id` | Delete a specific memory |
| `list_memories` | `limit` (default 20) | List everything stored for this workspace |

`tags` is a comma-separated string (e.g. `"convention, testing"`). Tagging
consistently makes both `recall` and the automatic injection more precise —
common tags include `convention`, `preference`, `architecture`, `config`, and
`issue`.

**Example usage by the agent:**
```
remember("Uses uv for dependency management, not pip directly.", tags="convention")
recall(tags="convention")
→ {found: true, memories: [{content: "Uses uv for dependency management...", tags: ["convention"], ...}]}
```

## Using memory

### Automatic (the normal case)

You don't need to do anything — the agent stores and recalls memories on its
own as it works:

```
❯ We use uv instead of pip for this project
  > remember: "Uses uv for dependency management, not pip directly." (tags: convention)

# ...in a later session...
❯ Add a new dependency
  [relevant memories already in context, including the uv convention above]
  > execute_shell: uv add <package>
```

### Manual

```
❯ /memories
Workspace memories (2):

  a1b2c3d4  Uses uv for dependency management, not pip directly. [convention]
  e5f6a7b8  User prefers tabs over spaces [preference]

❯ /remember Always run the linter before committing
Stored in memory: Always run the linter before committing

❯ /forget a1b2c3d4
Memory a1b2c3d4 has been deleted.
```

## Configuration

Memory tools (`remember`, `recall`, `forget`, `list_memories`) can be disabled
via the `memory` flag in `~/.clanker/config.yaml`:

```yaml
tools:
  memory: false
```

When disabled, the agent loses access to all four tools, the automatic
memory-injection at conversation start is skipped, and the tools' docs are
stripped from the system prompt. See
[Configuration → Tool Feature Flags](configuration.md#tool-feature-flags)
for details.
