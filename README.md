# Clanker

An AI-powered coding assistant CLI built with LangChain and LangGraph.

## Features

- **Interactive REPL**: Conversational interface for coding tasks
- **File Operations**: Read, write, and edit files with precision
- **Code Search**: Find files with glob patterns, search content with regex
- **Shell Commands**: Execute bash commands safely with sandboxing
- **Streaming Output**: Real-time response streaming for better UX
- **Session Persistence**: Resume conversations across sessions
- **Multi-Provider**: Support for Azure OpenAI, Anthropic (Claude), and OpenAI

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/clanker.git
cd clanker

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e ".[dev]"
```

## Configuration

### Quick Start with Azure OpenAI (Recommended)

1. Copy the example environment file:
```bash
cp .env.example .env
```

2. Configure your Azure OpenAI credentials:
```bash
AZURE_OPENAI_API_KEY=your-azure-api-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=your-deployment-name
```

3. Run Clanker with Azure:
```bash
clanker --provider azure
```

### Provider Configuration

Clanker supports multiple LLM providers:

| Provider | Environment Variables | Example Model |
|----------|----------------------|---------------|
| `azure` | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME` | gpt-4o |
| `anthropic` | `ANTHROPIC_API_KEY` | claude-sonnet-4-20250514 |
| `openai` | `OPENAI_API_KEY` | gpt-4o |

### Config File

Create a config file at `~/.clanker/config.yaml` for persistent settings:

```yaml
model:
  provider: azure  # or: anthropic, openai
  name: gpt-4o
  temperature: 0.7

  # Azure-specific settings (only needed for azure provider)
  azure:
    deployment_name: your-deployment-name
    api_version: "2024-02-15-preview"

safety:
  require_confirmation: true
  sandbox_commands: true

output:
  syntax_highlighting: true
  show_tool_calls: true
  stream_responses: true
```

### Environment Variables Reference

```bash
# Azure OpenAI
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=your-deployment

# Anthropic
ANTHROPIC_API_KEY=your-key

# OpenAI
OPENAI_API_KEY=your-key

# Override defaults via environment
CLANKER_MODEL__PROVIDER=azure
CLANKER_MODEL__NAME=gpt-4o
CLANKER_MODEL__AZURE__API_VERSION=2024-02-15-preview
```

## Usage

### Interactive Mode

```bash
# Start with default provider (from config or anthropic)
clanker

# Start with Azure OpenAI
clanker --provider azure

# Start with a specific model
clanker --provider azure --model gpt-4o

# Short form
clanker -p azure -m gpt-4o
```

### Single Prompt

```bash
# Run a single prompt
clanker "Explain the code in src/main.py"

# With Azure
clanker -p azure "Find all Python files in this project"
```

### Commands

Inside the interactive session:

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/clear` | Clear conversation history |
| `/model` | Show current model |
| `/config` | Show configuration |
| `/mcp` | Show MCP server status |
| `/exit` | Exit Clanker |

## Available Tools

The agent has access to these tools:

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents with line numbers |
| `write_file` | Create or overwrite files |
| `append_file` | Append content to files |
| `edit_file` | Make targeted string replacements |
| `list_directory` | List directory contents |
| `bash` | Execute shell commands |
| `glob_search` | Find files by pattern |
| `grep_search` | Search file contents with regex |

## MCP Servers

Clanker supports [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) servers, allowing you to extend the agent with external tools.

### Configuring MCP Servers

Add MCP servers to your `~/.clanker/config.yaml`:

```yaml
mcp:
  enabled: true
  servers:
    # Filesystem server (stdio transport)
    filesystem:
      transport: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/dir"]

    # Custom server with environment variables
    my-server:
      transport: stdio
      command: python
      args: ["/path/to/my_mcp_server.py"]
      env:
        API_KEY: "your-api-key"

    # SSE transport (for remote servers)
    remote-api:
      transport: sse
      url: http://localhost:8000/mcp/sse
```

### Supported Transports

| Transport | Description |
|-----------|-------------|
| `stdio` | Launches server as subprocess, communicates via stdin/stdout |
| `sse` | Connects to server via Server-Sent Events (HTTP) |

### MCP Tool Display

MCP tools are displayed with their server name prefix:
```
  > [filesystem] read_file: /path/to/file.txt
  > [my-server] custom_tool: query
```

### Popular MCP Servers

- `@modelcontextprotocol/server-filesystem` - File system access
- `@modelcontextprotocol/server-github` - GitHub integration
- `@modelcontextprotocol/server-postgres` - PostgreSQL database
- `@modelcontextprotocol/server-slack` - Slack integration

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

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=clanker

# Run specific test file
pytest tests/test_tools.py
```

### Code Quality

```bash
# Format and lint
ruff check --fix .
ruff format .

# Type checking
mypy src/clanker
```

## Architecture

```
clanker/
├── src/clanker/
│   ├── agent/       # LangGraph agent definition
│   ├── tools/       # Tool implementations
│   ├── memory/      # Session persistence
│   ├── ui/          # Console and streaming
│   ├── config/      # Settings management
│   ├── utils/       # Validators and sandbox
│   └── cli.py       # Main CLI entry point
└── tests/           # Test suite
```

## Safety

Clanker includes several safety features:

- **Command Sandboxing**: Dangerous commands are blocked
- **Path Protection**: System directories are protected from writes
- **Confirmation Prompts**: Destructive operations require confirmation
- **Output Limits**: Large outputs are truncated to prevent issues

## Troubleshooting

### Azure OpenAI Issues

**"AZURE_OPENAI_API_KEY not set"**
- Ensure your `.env` file exists and contains `AZURE_OPENAI_API_KEY`
- Or export it: `export AZURE_OPENAI_API_KEY=your-key`

**"AZURE_OPENAI_ENDPOINT not set"**
- Add your Azure endpoint: `AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/`

**"Azure deployment name not set"**
- Set `AZURE_OPENAI_DEPLOYMENT_NAME` in your environment
- Or configure `model.azure.deployment_name` in your config file

### Finding Your Azure OpenAI Details

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to your Azure OpenAI resource
3. Find **Keys and Endpoint** for your API key and endpoint
4. Go to **Model deployments** to find your deployment name

## License

MIT License - see LICENSE file for details.
