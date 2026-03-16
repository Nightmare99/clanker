# Clanker

An AI-powered coding assistant CLI built with LangChain and LangGraph.

## Features

- Interactive REPL with streaming responses
- File operations: read, write, edit, search
- Shell command execution with sandboxing
- Session persistence and conversation history
- Multi-provider: Anthropic, OpenAI, Azure OpenAI
- Web-based configuration UI
- MCP server support for extensibility

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Set your API key
export ANTHROPIC_API_KEY=your-key

# Run
clanker
```

Or with Azure OpenAI:

```bash
export AZURE_OPENAI_API_KEY=your-key
export AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
export AZURE_OPENAI_DEPLOYMENT_NAME=your-deployment

clanker -p azure
```

## Usage

```bash
clanker                        # Interactive mode
clanker "explain main.py"      # Single prompt
clanker config                 # Web configuration UI
clanker -p azure -m gpt-4o     # Specify provider/model
clanker --resume <session-id>  # Resume conversation
```

## Documentation

| Topic | Description |
|-------|-------------|
| [Configuration](docs/configuration.md) | Config file, web UI, environment variables |
| [Usage Guide](docs/usage.md) | Commands, interactive mode, examples |
| [Tools](docs/tools.md) | Available tools and their usage |
| [MCP Servers](docs/mcp.md) | Extending with Model Context Protocol |
| [Logging](docs/logging.md) | Log configuration and viewing |
| [Development](docs/development.md) | Setup, testing, architecture |
| [Troubleshooting](docs/troubleshooting.md) | Common issues and solutions |

## License

MIT License - see LICENSE file for details.
