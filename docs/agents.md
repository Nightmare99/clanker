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
   event loop. Its full output streams live to the user terminal. The return
   value to the parent agent is only a brief summary.

## Locations

Agents are discovered from two places:

| Location | Scope | Use for |
|----------|-------|---------|
| `.clanker/agents/` | **Project** (committed to the repo) | Agents specific to this codebase |
| `~/.clanker/agents/` | **Personal** (apply to every project) | Reusable agents across all projects |

If a project agent and a personal agent share the same name, the **project**
agent wins.

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

\* `name` is optional but recommended; without it the filename is used.

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
  > [subagent streams its analysis live]
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
| **Output** | Main agent responds | Main agent responds | Subagent streams live, parent gets summary |
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

Subagent tools (`load_agent`, `spawn_subagent`) can be disabled via the
`subagents` flag in `~/.clanker/config.yaml`:

```yaml
tools:
  subagents: false
```

When disabled, the agent won't have access to `load_agent` or `spawn_subagent`,
and the agents catalog won't be injected into the system prompt.

See [Configuration → Tool Feature Flags](configuration.md#tool-feature-flags) for
details.
