# Agents

Agents are specialized subagents with custom system prompts. Unlike
[skills](skills.md) (which provide instructions the main agent follows), agents
run **independently** with their own system prompt, tool access, and streaming
output. The main agent spawns an agent to delegate a subtask.

## How it works

1. **Always-on catalog**: every agent's `name` and `description` are injected
   into the system prompt under an `AVAILABLE AGENTS` section.
2. **On-demand loading**: when a task matches an agent's description, the main
   agent calls `load_agent` to retrieve the agent's full configuration, then
   `spawn_subagent` to run it.
3. **Isolated execution**: the subagent runs in its own thread with its own
   event loop. Progress and results appear in the F2 task panel. The parent
   receives a task ID, status, a bounded report and command evidence.

## Output conciseness

Every subagent's system prompt has conciseness instructions appended
automatically, asking it to keep its final response short and to the point.
This is backed by a hard limit: if a subagent's final response exceeds 800
words, Clanker truncates it before returning it to the parent agent, writes
the full untruncated text to a temporary file, and appends a note with the
word count and file path so the parent (or you) can read the rest if needed.
The full response remains available in the F2 task panel.

## Progress and history

Press **F2** or use `/tasks` to inspect all tasks started in this session. Each
entry shows its assignment, task ID, status, elapsed time, model, token budget,
usage, cost, changed files from file tools, and tool history. Enter a follow-up
and press **Send** to queue it for the next model boundary, or press **Stop** to
cancel that task. Pending follow-ups remain visible, including messages that
arrived too late to be consumed. Completed runs remain available across turns.

Task questions and shell approvals appear inside the TUI, one at a time. They
remain cancellable and count against the time budget. Without a TUI, a task
that requires input returns `needs_input`; the parent can resolve it and start
another task. Approval policy still applies to subagent shell commands.

## Managed execution

`spawn_subagent` still waits for completion by default. Set `background=True`
to receive a task ID immediately and continue independent work. The parent can
use these tools:

| Tool | Purpose |
|------|---------|
| `subagent_status(task_id)` | Get progress, result, usage and command evidence; omit the ID to list tasks. |
| `subagent_message(task_id, message)` | Queue follow-up instructions for a running task. |
| `subagent_stop(task_id)` | Cancel a queued or running task. |
| `subagent_wait(task_id, timeout_seconds=30)` | Wait up to 60 seconds and return current status. |

The default concurrency limit is three tasks. Further tasks queue until a slot
opens. Task IDs and results are in-memory and last for this process, not across
restarts. `success` describes a completed execution, not independently verified
correctness; the parent still reviews the result. Command evidence records
executed shell commands and their outcomes, not an automatic test certification.

Each task has time and token budgets. Optional `timeout_seconds` and `max_tokens`
arguments can lower the configured limits. Token limits use provider-reported
usage, are checked after each model response, and may overshoot by one response.
Time limits start when a task leaves the queue. Repeated identical tool failures
stop a task as `stalled`. Other incomplete states include `cancelled`, `timed_out`,
`budget_exceeded`, `step_limit`, `needs_input` and `error`. Cancellation is
cooperative: a task remains `stopping` until in-flight operations and cleanup
return, including any worktree preparation already in progress.

Managed tasks cannot spawn nested agents or use detached background-job tools.
Their `execute_shell` commands stay attached to the task, use its working
directory, and are stopped on cancellation or timeout. Process-group cleanup
is supported on POSIX; Windows currently terminates the direct shell process.

### Separate worktrees for writers

Set `isolation="worktree"` when delegating concurrent edits. Clanker creates a
separate detached Git worktree and copies the current tracked changes plus
non-ignored untracked files. Ignored dependencies/configuration are not copied,
and untracked symlinks are rejected. A repository with an existing commit is
required. The task's working directory is returned in its result.

The worktree is retained for review and recovery, including after cancellation.
The parent must inspect and integrate the changes; nothing is automatically
merged into the original workspace. Worktrees isolate ordinary relative file
edits and command working directories, not OS permissions or absolute paths.
Use `isolation="shared"` (the default) only for non-overlapping work.

Configure limits in `~/.clanker/config.yaml`:

```yaml
subagents:
  max_concurrent: 3
  timeout_seconds: 900
  max_tokens: 200000
  repeated_failure_limit: 3
```

## Locations

Agents are discovered from up to four places, in this precedence order
(earlier wins on a name collision):

| Location | Scope | Use for |
|----------|-------|---------|
| `.clanker/agents/` | **Project** (committed to the repo) | Agents specific to this codebase |
| `~/.clanker/agents/` | **Personal** (apply to every project) | Reusable agents across all projects |
| `.agents/agents/` | **Project**, `.agents` fallback | Agents authored for other agentic coding tools |
| `~/.agents/agents/` | **Personal**, `.agents` fallback | Personal agents shared across tools via `.agents` |

`.agents/` is an emerging cross-tool convention some agentic coding tools use
for shared configuration. Clanker reads it as a fallback so an agent written
for another tool works here too — but `.clanker/` is always checked first, at
both the project and personal tier, so it wins any name collision against
`.agents/`.

## Agent format

Each agent is a markdown file with YAML frontmatter:

```
.clanker/agents/
  code-explorer.md
  test-runner.md
```

**`.clanker/agents/code-explorer.md`**:

```markdown
---
name: code-explorer
description: Explores and explains codebases. Use when the user wants to understand project structure, how code works, or trace data flow.
tools: [read_file, glob_search, grep_search]
model: claude-haiku  # optional; uses the session's default model if omitted
---

# Code Explorer

You are a codebase exploration specialist. Your job is to help users understand
how a project works by examining its structure, tracing data flow, and
explaining architecture decisions.

When exploring:
1. Start with the project root to understand the layout.
2. Look at key files (main entry point, config, dependencies).
3. Trace the flow from entry point to the feature in question.
4. Summarize findings clearly.
```

### Frontmatter fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | No* | Canonical agent id. Defaults to the filename (without `.md`). |
| `description` | **Yes** | What the agent does and when to use it. This is the trigger signal the main agent matches against. |
| `tools` | No | List of tool names the agent should have access to. If omitted or empty, the agent gets all default tools. |
| `model` | No | Name of a model configured in `~/.clanker/models.json` to run this agent with. If omitted, the agent uses the session's default model. |

\* `name` is optional but recommended; without it the filename is used.

Pinning a `model` is useful for giving a fast/cheap model to simple, high-volume
subagents (e.g. an exploration agent) while keeping the main conversation on a
stronger model. If the named model isn't found in `models.json`, the agent
falls back to the session default and a warning is logged.

### Body

The body is free-form markdown that serves as the agent's **system prompt**.
Write it as you would any system prompt — it defines the agent's behavior,
personality, and working methodology.

The body is truncated to **15,000 characters** to prevent oversized prompts.

## Using agents

### Automatic (the normal case)

Just make a request. If it matches an agent's description, the main agent loads
and spawns it:

```
❯ How does authentication work in this project?
  > load_agent: code-explorer
  > spawn_subagent: code-explorer
  ┌─ Agent 'code-explorer' started
  > [inspect progress and results with F2]
  └─ Agent 'code-explorer' completed
```

### Manual

You can inspect agent configuration by having the agent call `load_agent`:

```
❯ Load the configuration for the code-explorer agent
  > load_agent: code-explorer
  → {name: "code-explorer", description: "...", system_prompt: "...", ...}
```

## Agents vs. skills

| | Workflows | Skills | Agents |
|---|-----------|--------|--------|
| **Triggered by** | You, via `/workflow` | The agent, automatically | The agent, automatically |
| **Format** | A single `.md` file | A directory with `SKILL.md` + files | A single `.md` file with frontmatter |
| **Execution** | Prompt injected into main agent | Main agent follows instructions | Independent subagent with own prompt |
| **In context** | Whole file injected | Only name + description, until loaded | Only name + description, until spawned |
| **Output** | Main agent responds | Main agent responds | Task panel shows progress; parent gets structured result |
| **Best for** | Repeatable prompts you invoke | Procedures the agent follows | Delegating subtasks to a specialist |

Use a **workflow** when you want a canned prompt you fire deliberately. Use a
**skill** when you want the agent to follow a procedure. Use an **agent** when
you want to delegate a subtask to an independent specialist.

## Tool restrictions

An agent can restrict which tools it has access to via the `tools` frontmatter
field. This is useful for agents that only need a subset of capabilities:

```yaml
tools: [read_file, glob_search, grep_search]
```

The agent will only have access to the named tools. Tool names must match the
`name` attribute of the tool (e.g. `read_file`, not `read`).

## Disabling subagents

Subagent tools (`load_agent`, `spawn_subagent`, and `subagent_*`) can be disabled via the
`subagents` flag in `~/.clanker/config.yaml`:

```yaml
tools:
  subagents: false
```

When disabled, the agent won't have access to any subagent tools,
and the agents catalog won't be injected into the system prompt.

See [Configuration → Tool Feature Flags](configuration.md#tool-feature-flags) for
details.
