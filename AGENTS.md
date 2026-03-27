# AGENTS.md

## Project Overview
**Clanker** is an AI-powered coding assistant CLI built with **LangChain** and **LangGraph**. It provides an interactive REPL and single-prompt mode for performing coding tasks such as reading/editing files, searching codebases, and running shell commands with safety controls.

This file is intended for **LLMs and autonomous agents** to quickly understand the project structure, goals, conventions, and safe operating boundaries.

---

## Primary Goals
- Provide a **developer-grade coding assistant** via CLI
- Enable **safe, auditable file and command operations**
- Support **multiple LLM providers** (Azure OpenAI, OpenAI, Anthropic)
- Be **extensible** via Model Context Protocol (MCP) servers

---

## How Clanker Is Used
Clanker is invoked either interactively or with a single prompt:

```bash
clanker                    # interactive REPL
clanker "Explain src/main.py"  # single-shot prompt
```

Inside the REPL, users issue natural language instructions. The agent decides when to call tools.

---

## Agent Capabilities (Mental Model)
An LLM acting inside Clanker should behave as:
- A **coding partner**, not a chatbot
- Action-oriented: read files, make edits, run tests
- Careful and precise: read before writing, minimal diffs
- Safety-aware: destructive operations require confirmation

---

## Available Tools
The agent has access to the following first-party tools:

| Tool | Purpose |
|-----|--------|
| `read_file` | Read file contents with line numbers |
| `write_file` | Create or overwrite a file |
| `append_file` | Append content to a file |
| `edit_file` | Targeted string replacement (context must be unique) |
| `list_directory` | List directory contents |
| `glob_search` | Find files by glob pattern |
| `grep_search` | Search file contents using regex |
| `bash` | Execute shell commands (sandboxed) |
| `notify` | Send an immediate status update to the user mid-execution |

Additional tools may be exposed via **MCP servers**.

---

## Safety Model (Critical for Agents)
Agents MUST respect the following constraints:

- **No blind writes**: always read files before editing
- **No system paths**: writing to `/etc`, `/usr`, etc. is blocked
- **Destructive commands** (`rm -rf`, force pushes, etc.) require explicit user confirmation
- **Secrets**: API keys and credentials must never be echoed or logged
- **Large outputs** are truncated automatically

---

## Repository Structure

```
clanker/
├── src/clanker/
│   ├── agent/       # LangGraph agent logic
│   ├── tools/       # Tool implementations
│   ├── memory/      # Session persistence
│   ├── ui/          # CLI, streaming output
│   ├── config/      # Configuration handling
│   ├── utils/       # Validation, sandboxing
│   └── cli.py       # CLI entry point
├── tests/           # Pytest suite
├── README.md        # Human-facing documentation
├── REQUIREMENTS.md  # Detailed requirements and design notes
└── pyproject.toml   # Build and dependency configuration
```

---

## Configuration Sources
Settings come from:
1. `~/.clanker/models.json` - Model configurations (provider, API keys, etc.)
2. `~/.clanker/config.yaml` - General settings (safety, output, context management)
3. Environment variables (`AZURE_OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`)
4. CLI flags (`--provider`, `--model`, etc.)

Agents should assume configuration is already loaded and valid.

---

## LLM Provider Abstraction
Clanker supports multiple providers via a unified interface:

- **AzureOpenAI** - Azure-hosted OpenAI models
- **OpenAI** - Direct OpenAI API
- **Anthropic** - Claude models with extended thinking support
- **Ollama** - Local models

Provider choice should not affect agent behavior, only model quality.

---

## MCP (Model Context Protocol)
Clanker can load external tools via MCP servers:
- Filesystem
- GitHub
- Databases
- Custom APIs

Agents will see MCP tools prefixed with the server name, e.g.:

```
[filesystem] read_file
[github] create_issue
```

Agents should treat MCP tools as first-class but potentially slower or less reliable than local tools.

---

## Testing & Quality
- Tests are written with **pytest**
- Formatting and linting via **ruff**
- Type checking via **mypy**

Agents modifying code should:
- Prefer minimal diffs
- Avoid refactors unless requested or clearly beneficial
- Suggest tests when behavior changes

---

## What NOT to Do (Agent Anti-Patterns)
- Do NOT ask unnecessary permission for safe actions
- Do NOT modify unrelated files
- Do NOT invent files, APIs, or config options
- Do NOT expose secrets from `.env`

---

## If You Are an LLM Reading This
Your job is to:
1. Understand the user's intent
2. Inspect the codebase as needed
3. Take decisive, correct action using tools
4. Explain what you changed and why

Clanker is designed for **execution**, not speculation.

---

_End of AGENTS.md_