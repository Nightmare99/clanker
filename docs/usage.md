# Usage

## Operational Modes

Clanker supports two modes:

| Mode | Command | Description |
|------|---------|-------------|
| **BYOK** | `clanker` | Bring Your Own Key - uses your configured API keys |
| **Copilot** | `clanker --copilot` | Uses GitHub Copilot with native SDK session management |

See [Copilot Mode](copilot.md) for details on using GitHub Copilot.

## CLI Flags

| Flag | Short | Description |
|------|-------|-------------|
| `--help` | `-h` | Show help and exit |
| `--version` | `-v` | Show version and exit |
| `--check-update` | | Check for updates and exit |
| `--model <name>` | `-m` | Use a specific model |
| `--provider <name>` | `-p` | Use a specific provider (BYOK mode only) |
| `--resume <id>` | `-r` | Resume a previous session |
| `--history` | | List past conversations |
| `--memories` | | Show stored memories |
| `--yolo` | | Skip bash command approval |
| `--copilot` | | Use GitHub Copilot mode |

## Interactive Mode

```bash
# Start with default model (BYOK mode)
clanker

# Start in Copilot mode
clanker --copilot

# Start with a specific model (from models.json)
clanker -m "Claude Sonnet"

# Copilot mode with specific model
clanker --copilot -m claude-sonnet-4

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

By default, all bash commands require approval before execution. When the AI wants to run a command, you'll see an approval prompt:

```
╭─────────────────────────────────────────────────────────────╮
│  Bash Command                                               │
├─────────────────────────────────────────────────────────────┤
│  $ npm test
├─────────────────────────────────────────────────────────────┤
│  [y]es  execute     [N]o  reject and stop                   │
╰─────────────────────────────────────────────────────────────╯
Approve?
```

- Type `y` or `yes` to approve and execute the command
- Press Enter or type anything else to reject and stop

**Note:** Rejecting a command terminates the current AI response. This prevents the AI from trying alternative approaches after you've declined.

### Yolo Mode

If you trust the AI's commands and want to skip approval prompts, start Clanker with the `--yolo` flag:

```bash
clanker --yolo
```

In yolo mode, all bash commands execute automatically without asking for approval. A warning indicator will appear in the welcome message to remind you that this mode is active.

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
