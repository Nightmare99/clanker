# Clanker

An AI-powered coding assistant CLI built with LangChain and LangGraph.

## Features

- Interactive REPL with streaming responses
- File operations: read, write, edit, search
- Shell command execution with sandboxing
- [Web search and page reading](docs/tools.md#web_search) with domain and recency filters, plus Markdown extraction (no API key required)
- Session persistence and conversation history
- **Multi-provider support**: Anthropic, OpenAI, Azure OpenAI, Ollama, GitHub Copilot, Google Antigravity, ChatGPT (bring your own key, or connect a supported account)
- Easy model switching with `/model` command
- Extended thinking support for Claude models
- Web-based configuration UI (BYOK mode)
- MCP server support for extensibility

## Quick Start

### One-Line Install (Recommended)

**Linux / macOS:**
```bash
curl -fsSL https://raw.githubusercontent.com/Nightmare99/clanker/main/scripts/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/Nightmare99/clanker/main/scripts/install.ps1 | iex
```

This automatically detects your OS/architecture and installs the latest release.

### Manual Download

Download from [GitHub Releases](https://github.com/Nightmare99/clanker/releases):
- **Linux**: `clanker-linux-amd64.tar.gz`
- **macOS Intel**: `clanker-darwin-amd64.tar.gz`
- **macOS ARM**: `clanker-darwin-arm64.tar.gz`
- **Windows**: `clanker-windows-amd64.zip`

### From Source

```bash
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=your-key
clanker
```

## Usage

```bash
clanker                        # Interactive mode
clanker "explain main.py"      # Single prompt
clanker config                 # Web configuration UI
clanker copilot-login          # Connect a GitHub Copilot subscription
clanker antigravity-login      # Connect Google Antigravity (unofficial integration)
clanker openai-login           # Connect ChatGPT and discover available coding models
clanker -m claude              # Use a specific model
clanker --resume <session-id>  # Resume conversation
clanker --yolo                 # Auto-execute bash commands (skip approval)
clanker --check-update         # Check for updates
```

Inside Clanker, `/restore` (or `/resume`) opens a paginated conversation
picker. `/import` guides you through importing Codex, Claude Code, OpenCode,
or GitHub Copilot CLI sessions from the current workspace. See the
[usage guide](docs/usage.md#resuming-and-importing-conversations).

Google Antigravity uses browser login and discovers Claude/Gemini models without
a separate proxy. See [setup and account-risk notes](docs/configuration.md#google-antigravity).

ChatGPT login uses your account's available Codex models without an API key,
Node.js, or a separate proxy. Run `/openai-login` in a session or use the
**Sign in with ChatGPT** card in `clanker config`. See [ChatGPT setup](docs/configuration.md#chatgpt-openai-account).

## Documentation

| Topic | Description |
|-------|-------------|
| [Installation](docs/installation.md) | Pre-built binaries, pip, building from source |
| [Configuration](docs/configuration.md) | Config file, web UI, environment variables |
| [Usage Guide](docs/usage.md) | Commands, interactive mode, examples |
| [Tools](docs/tools.md) | Available tools and their usage |
| [Skills](docs/skills.md) | Model-discovered capabilities with bundled scripts |
| [MCP Servers](docs/mcp.md) | Extending with Model Context Protocol |
| [Logging](docs/logging.md) | Log configuration and viewing |
| [Development](docs/development.md) | Setup, testing, architecture |
| [Troubleshooting](docs/troubleshooting.md) | Common issues and solutions |

## License

MIT License - see LICENSE file for details.
