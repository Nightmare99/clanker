# Available Tools

The agent has access to these built-in tools:

| Tool | Category | Description |
|------|----------|-------------|
| `read_file` | Core | Read file contents with line numbers |
| `write_file` | Core | Create or overwrite files |
| `append_file` | Core | Append content to files |
| `edit_file` | Core | Make targeted string replacements |
| `list_directory` | Core | List directory contents |
| `execute_shell` | Core | Execute shell commands |
| `bash_background` | Core | Launch a long-running command in the background |
| `bash_status` | Core | Inspect background job state |
| `bash_output` | Core | Read captured background job output |
| `bash_wait` | Core | Block until a background job finishes |
| `bash_kill` | Core | Terminate a background job |
| `glob_search` | Core | Find files by pattern |
| `grep_search` | Core | Search file contents with regex |
| `web_search` | Web Browsing | Search the web via DuckDuckGo |
| `web_read` | Web Browsing | Extract clean content from a web page |
| `remember` | Memory | Store info for future sessions |
| `recall` | Memory | Retrieve relevant memories |
| `forget` | Memory | Delete a stored memory |
| `list_memories` | Memory | List all stored memories |
| `load_skill` | Skills | Load instructions for a skill |
| `load_agent` | Subagents | Load configuration for an agent |
| `spawn_subagent` | Subagents | Spawn a configured subagent to handle a subtask |
| `notify` | Communication | Send an immediate status update to the user |
| `ask_user` | Communication | Ask the user a multiple-choice question mid-task |

## Tool Categories

Tools are grouped into categories that can be individually enabled or disabled
via the `tools` section in `~/.clanker/config.yaml` or the **Tools** tab in the
web configuration UI (`clanker config`).

| Category | Flag | Tools | Default |
|----------|------|-------|---------|
| Core | — | `read_file`, `write_file`, `edit_file`, `append_file`, `list_directory`, `execute_shell`, `bash_background`, `bash_status`, `bash_output`, `bash_wait`, `bash_kill`, `glob_search`, `grep_search` | Always on |
| Web Browsing | `web_browsing` | `web_search`, `web_read` | Enabled |
| Memory | `memory` | `remember`, `recall`, `forget`, `list_memories` | Enabled |
| Skills | `skills` | `load_skill` | Enabled |
| Subagents | `subagents` | `load_agent`, `spawn_subagent` | Enabled |
| Communication | `communication` | `notify`, `ask_user` | Enabled |

**Core tools** cannot be disabled — the agent requires them to function. All other
categories can be toggled off. When a category is disabled, its tools are removed
from the agent's tool list and their documentation is stripped from the system
prompt, saving context window tokens.

See [Configuration → Tool Feature Flags](configuration.md#tool-feature-flags) for
details on how to disable categories.

## Tool Details

### read_file

Reads a file and returns its contents with line numbers.

### write_file

Creates a new file or overwrites an existing file with the provided content.

### append_file

Appends content to the end of an existing file.

### edit_file

Makes precise string replacements in a file. Useful for targeted edits without rewriting the entire file.

### list_directory

Lists files and directories at a given path.

### execute_shell

Executes shell commands in a sandboxed environment. Dangerous commands are blocked by default.

### glob_search

Finds files matching a glob pattern (e.g., `**/*.py`, `src/**/*.js`).

### grep_search

Searches file contents using regular expressions. Returns matching lines with context.

### web_search

Searches the web using DuckDuckGo. No API key required.

**Parameters:**
- `query` — Search query string. Be specific for best results.
- `max_results` — Number of results to return (1–10, default 5).

**Returns:** Titles, URLs, and content snippets for each result.

**Example usage by the agent:**
```
web_search("python asyncio gather exception handling", max_results=3)
```

### web_read

Fetches a web page and extracts the main content as clean text, stripping navigation, ads, scripts, and boilerplate HTML.

**Parameters:**
- `url` — The URL to read (must start with `http://` or `https://`).
- `max_length` — Maximum characters to return (1000–50000, default 20000).

**Returns:** Clean extracted text content from the page.

**Notes:**
- Uses browser-like headers to avoid bot detection on most sites.
- Falls back to an alternative fetcher if the primary method fails.
- Some sites with aggressive anti-bot protection (Cloudflare JS challenges) cannot be read. The tool will return an HTTP error code in those cases.

**Example workflow:**
```
web_search("fastapi middleware order")  → finds relevant docs page
web_read("https://fastapi.tiangolo.com/advanced/middleware/")  → reads full content
```

## Web Search Configuration

Web search is enabled by default. To disable it, add to `~/.clanker/config.yaml`:

```yaml
web_search:
  enabled: false
```

When disabled, `web_search` and `web_read` are removed from the agent entirely (no wasted prompt tokens).

## Asking the User (`ask_user`)

When the agent hits a genuine fork it can't resolve on its own, it can pause and
ask you a multiple-choice question, then continue in the same turn with your
answer.

**Parameters:**
- `question` — the question to ask.
- `options` — 2–10 short option labels.
- `multi_select` — allow picking more than one option (default `false`).
- `allow_other` — offer a free-text "Other" answer (default `true`).
- `allow_cancel` — allow cancelling without choosing (default `true`).

**How you answer:**
- On a real terminal you get an **arrow-key menu** — ↑/↓ to move, space to toggle
  (multi-select), Enter to confirm, Esc to cancel.
- When input isn't a terminal (piped input, one-shot `clanker "prompt"`, CI) it
  falls back to a **numbered list** — type the number(s), `0` or blank to cancel,
  `o` for a custom answer.

**When the agent uses it:** only at real decision points — which environment to
deploy to, which of several ambiguous scopes to take, or a choice between
materially different approaches. It won't use it for decisions it can make itself
or for routine bash confirmations (those have their own approval prompt).

## Background Shell Jobs

For long-running commands (tests, builds, dev servers), the agent can launch
them in the background and keep working:

- **`bash_background(command, name, timeout)`** — Launch a command in the
  background; returns a job id immediately. Always pass a short `name`
  (e.g. "pytest suite", "vite dev") so jobs are distinguishable.
- **`bash_status(job_id)`** — Inspect a job's state, return code, runtime,
  and output size. Without `job_id`, lists all jobs.
- **`bash_output(job_id, tail, since_byte)`** — Read captured output. Use
  `since_byte` from a previous read to poll incrementally.
- **`bash_wait(job_id, timeout)`** — Block until a job finishes; returns
  final status and output. Use when your next step depends on the result.
- **`bash_kill(job_id)`** — Terminate a background job.

## Subagents

Subagents let the agent delegate subtasks to specialized agents with their own
system prompts. See [Agents](agents.md) for how to create and configure agents.

### load_agent

Load the configuration for an available agent by name. Returns the agent's
system prompt, tool restrictions, and metadata. Call this before spawning the
agent with `spawn_subagent`.

**Parameters:**
- `name` — Agent name exactly as shown in the AVAILABLE AGENTS catalog.

**Returns:** A dict with `system_prompt`, `tools`, `description`, and `source`.

### spawn_subagent

Spawn a configured subagent to handle a subtask in a separate thread. The
subagent runs with its own event loop, its own streaming output, and its own
tool set. Its full output is streamed live to the user terminal. The return
value contains only a brief summary.

**Parameters:**
- `agent_name` — Name of the agent to spawn.
- `prompt` — Detailed instructions for the subagent.

**Returns:** A dict with `summary`, `input_tokens`, and `output_tokens`.

**Example workflow:**
```
load_agent("code-explorer")           → get agent config
spawn_subagent("code-explorer",       → subagent runs, streams output live
  "Explain how authentication works")
→ parent agent reads summary, moves on
```

## MCP Tools

Additional tools can be loaded from [MCP servers](mcp.md). These appear with a server prefix:

```
[filesystem] read_file
[github] create_issue
```
