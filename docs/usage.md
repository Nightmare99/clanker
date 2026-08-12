# Usage

## CLI Flags

| Flag | Short | Description |
|------|-------|-------------|
| `--help` | `-h` | Show help and exit |
| `--version` | `-v` | Show version and exit |
| `--check-update` | | Check for updates and exit |
| `--model <name>` | `-m` | Use a specific model |
| `--provider <name>` | `-p` | Use a specific provider |
| `--resume <id>` | `-r` | Resume a previous session |
| `--history` | | List past conversations |
| `--memories` | | Show stored memories |
| `--yolo` | | Skip bash command approval |

## Interactive Mode

```bash
# Start with default model
clanker

# Start with a specific model (from models.json)
clanker -m "Claude Sonnet"

# Resume a previous session
clanker --resume <session-id>

# Skip bash command approval (yolo mode)
clanker --yolo

# Check for updates
clanker --check-update
```

## Single Prompt

```bash
# Run a single prompt and exit
clanker "Explain the code in src/main.py"

# With specific provider
clanker -p AzureOpenAI "Find all Python files in this project"
```

## Commands

Inside the interactive session:

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/clear` | Clear conversation history |
| `/model` | List available models and show current |
| `/model <name>` | Switch to a different model |
| `/copilot-login` | Connect a GitHub Copilot subscription as a model provider |
| `/workflow` | List available workflows |
| `/workflow <name>` | Execute a stored workflow |
| `/skill` | List available skills |
| `/skill <name>` | Manually load a skill (the agent also loads skills automatically) |
| `/config` | Show configuration |
| `/mcp` | Show MCP server status |
| `/logs` | Show logging status and log files |
| `/history` | List past conversations |
| `/restore <id>` | Restore a previous session |
| `/memories` | Show stored memories |
| `/remember <text>` | Save a memory |
| `/forget <id>` | Delete a memory |
| `/exit` | Exit Clanker |

### Switching Models

You can switch between configured models during a session:

```
❯ /model
Current model: Claude Sonnet (Anthropic)

Available models:
  Claude Sonnet (Anthropic) *
  GPT-4o (AzureOpenAI)
  Llama Local (Ollama)

Use /model <name> to switch models.

❯ /model GPT-4o
Switched to model: GPT-4o (AzureOpenAI)
```

Models are configured in `~/.clanker/models.json` or via `clanker config`.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Tab` | While typing a slash command (e.g. `/model `, `/workflow `, `/skill `, `/restore `), opens the completion menu and gives it keyboard control. Press `Tab` again to accept the highlighted match. |
| `↑` / `↓` | Navigate input history, or — once the completion menu has keyboard control (after pressing `Tab`) — move the highlight up/down within it. |
| `Alt+↑` / `Alt+↓` | Navigate input history even while the completion menu has keyboard control. |
| `Enter` | Submit the input, or — with the completion menu engaged — accept the highlighted match. |
| `Ctrl+C` | Copy the current text selection, if any (in-field or screen-wide). If nothing is selected, interrupts the agent instead. |
| `Ctrl+D` | Quit Clanker. |
| `F2` | Open the **Subagents** panel — view past and in-flight subagent runs, their prompts, status, and tool call history for the session (see [Agents → Progress and history](agents.md#progress-and-history)). |
| `F3` | Open the **History** panel — the full conversation so far, independent of how much the chat log has trimmed from view (see [TUI Performance](configuration.md#tui-performance)) and populated even after `/restore`, when the restored turns aren't replayed into the chat log. |
| `Esc` | Cancel an open menu or approval prompt. |

Input history is persisted across sessions to `~/.clanker/input_history.txt`
(last 500 entries).

### Sending Messages While the Agent Is Working

You can type and submit a follow-up message while the agent is still
processing a previous turn — it doesn't need to finish first. The message is
queued (shown above the input bar) and injected as soon as the agent reaches
its next step, rather than being dropped or requiring you to wait. Slash
commands are not queued this way; they still require the agent to be idle.

## Examples

### Reading and Understanding Code

```
❯ Read the main.py file and explain what it does
```

### Making Edits

```
❯ In src/utils.py, change the function name from 'getData' to 'fetch_data'
```

### Searching the Codebase

```
❯ Find all files that import the 'requests' library
```

### Running Commands

```
❯ Run the tests and show me any failures
```

## Command Approval

By default, all bash commands require approval before execution. When the AI wants to run a command, you'll see an arrow-key menu showing the command and three choices:

```
  Bash Command
  $ npm test

  Run this command?
  ↑/↓ to move · enter to select · esc cancels

  ❯ Yes, execute
    Yes, and don't ask again (this session)
    No, reject and stop
```

- **Yes, execute** — run this command.
- **Yes, and don't ask again (this session)** — run it and stop prompting for the rest of the session (equivalent to enabling yolo mode until you exit).
- **No, reject and stop** — reject the command. Use ↑/↓ to move, Enter to select, and Esc to cancel.

When stdin isn't an interactive terminal (piped input, one-shot `clanker "prompt"`, CI), the prompt falls back to a numbered list — type `1`, `2`, or `3`.

**Note:** Rejecting a command terminates the current AI response. This prevents the AI from trying alternative approaches after you've declined.

### Yolo Mode

If you trust the AI's commands and want to skip approval prompts entirely from the start, launch Clanker with the `--yolo` flag:

```bash
clanker --yolo
```

In yolo mode, all bash commands execute automatically without asking for approval. A warning indicator will appear in the welcome message to remind you that this mode is active. (Choosing "Yes, and don't ask again" at an approval prompt turns this on mid-session.)

## Checking for Updates

Clanker can check for new releases on GitHub:

```bash
# Manual check
clanker --check-update
```

On startup, Clanker automatically checks for updates and shows a notification if a new version is available:

```
[Update Available]
v0.1.0 -> v0.2.0
Run: curl -fsSL https://raw.githubusercontent.com/Nightmare99/clanker/main/scripts/install.sh | bash
```

To update, run the install script - it will detect the existing installation and prompt before upgrading.
