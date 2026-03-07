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
| `/model` | Show current model |
| `/config` | Show configuration |
| `/mcp` | Show MCP server status |
| `/logs` | Show logging status and log files |
| `/history` | List past conversations |
| `/restore <id>` | Restore a previous session |
| `/memories` | Show stored memories |
| `/remember <text>` | Save a memory |
| `/forget <id>` | Delete a memory |
| `/exit` | Exit Clanker |

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
