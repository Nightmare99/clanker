# Usage

## Interactive Mode

```bash
# Start with default provider
clanker

# Start with specific provider
clanker --provider azure

# Start with a specific model
clanker --provider azure --model gpt-4o

# Short form
clanker -p azure -m gpt-4o

# Resume a previous session
clanker --resume <session-id>

# Skip bash command approval (yolo mode)
clanker --yolo
```

## Single Prompt

```bash
# Run a single prompt and exit
clanker "Explain the code in src/main.py"

# With specific provider
clanker -p azure "Find all Python files in this project"
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
