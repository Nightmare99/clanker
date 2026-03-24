# Clanker

An AI-powered coding assistant CLI built with LangChain and LangGraph.

## Features

- Interactive REPL with streaming responses
- File operations: read, write, edit, search
- Shell command execution with sandboxing
- Session persistence and conversation history
- Multi-provider: Anthropic, OpenAI, Azure OpenAI, Ollama
- Easy model switching with `/model` command
- Extended thinking support for Claude models
- Web-based configuration UI
- MCP server support for extensibility

## Quick Start

### Pre-built Binary (Recommended)

Download from [GitHub Releases](https://github.com/yourusername/clanker/releases):
- **Linux**: `clanker-linux-amd64.tar.gz`
- **macOS Intel**: `clanker-darwin-amd64.tar.gz`
- **macOS ARM**: `clanker-darwin-arm64.tar.gz`
- **Windows**: `clanker-windows-amd64.zip`

### From Source

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
| [Installation](docs/installation.md) | Pre-built binaries, pip, building from source |
| [Configuration](docs/configuration.md) | Config file, web UI, environment variables |
| [Usage Guide](docs/usage.md) | Commands, interactive mode, examples |
| [Tools](docs/tools.md) | Available tools and their usage |
| [MCP Servers](docs/mcp.md) | Extending with Model Context Protocol |
| [Logging](docs/logging.md) | Log configuration and viewing |
| [Development](docs/development.md) | Setup, testing, architecture |
| [Troubleshooting](docs/troubleshooting.md) | Common issues and solutions |

## License

MIT License - see LICENSE file for details.
