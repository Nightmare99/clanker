# GitHub Copilot Mode

Clanker supports two operational modes:

1. **BYOK Mode** (Bring Your Own Key) - Default mode using your own API keys
2. **Copilot Mode** - Uses GitHub Copilot with native SDK session management

## Quick Start

```bash
# Start in Copilot mode
clanker --copilot

# Start with a specific Copilot model
clanker --copilot -m claude-sonnet-4
```

On first run, you'll be prompted to authenticate with GitHub if not already logged in.

## Authentication

Before using Copilot mode, you need to authenticate with GitHub:

```bash
# Option 1: Run clanker --copilot (will prompt automatically)
clanker --copilot

# Option 2: Authenticate from within any session
❯ /gh-login
```

The authentication uses OAuth device flow:
1. Visit the URL shown in the terminal
2. Enter the device code
3. Authorize the Copilot application
4. Token is saved to `~/.clanker/copilot_token`

## Available Models

In Copilot mode, use `/model` to list available models:

```
❯ /model
Current model: gpt-4.1

Available Copilot models:
  gpt-4.1 (GPT-4.1)
  gpt-4.1-mini (GPT-4.1 Mini)
  claude-sonnet-4 (Claude Sonnet 4)
  claude-sonnet-4-thinking (Claude Sonnet 4 with Thinking)
  o3-mini (O3 Mini)
```

Switch models with `/model <model-id>`:

```
❯ /model claude-sonnet-4
Switched to Copilot model: claude-sonnet-4
```

**Note**: Model availability depends on your GitHub Copilot subscription.

## Session Management

Copilot mode uses the Copilot SDK's native session management, which provides:

- **Persistent Sessions**: Conversations are stored by the SDK
- **Infinite Sessions**: Automatic context compaction when approaching limits
- **Session Resume**: Continue past conversations across restarts

### Session Commands

| Command | Description |
|---------|-------------|
| `/history` | List Copilot sessions (shows session IDs) |
| `/restore <id>` | Resume a previous Copilot session |
| `/clear` | Start a fresh Copilot session |

### Session Storage

Sessions are stored by the Copilot SDK in:
```
~/.copilot/session-state/{session_id}/
```

Only sessions created by Clanker (prefixed with `clanker-`) are shown in `/history`.

## Mode Differences

| Feature | BYOK Mode | Copilot Mode |
|---------|-----------|--------------|
| API Keys | Your own keys required | GitHub Copilot subscription |
| Providers | Anthropic, OpenAI, Azure, Ollama | Copilot models only |
| Session Storage | `.clanker/conversations/` | `~/.copilot/session-state/` |
| Context Management | LangGraph summarization | SDK infinite sessions |
| `/model` | Shows BYOK models | Shows Copilot models |
| Web Config UI | Full configuration | Not applicable |
| MCP Integration | Via langchain-mcp-adapters | Native SDK support |
| Tool Isolation | All tools available | Only clanker + MCP tools |

## Switching Modes

Modes are mutually exclusive within a session. To switch modes:

```bash
# Start in BYOK mode (default)
clanker

# Start in Copilot mode
clanker --copilot
```

**Important**: You cannot switch between BYOK and Copilot modes within a running session. Session history is separate for each mode.

## CLI Flags

| Flag | Description |
|------|-------------|
| `--copilot` | Enable Copilot mode |
| `-m <model>` | Override the Copilot model (e.g., `-m claude-sonnet-4`) |
| `-r <id>` | Resume a Copilot session |
| `--yolo` | Skip bash command approval (works in both modes) |

## Environment Variables

Copilot authentication can also use these environment variables:

| Variable | Description |
|----------|-------------|
| `COPILOT_TOKEN` | Copilot OAuth token (primary) |
| `GH_TOKEN` | GitHub token (fallback) |
| `GITHUB_TOKEN` | GitHub token (fallback) |

If no token is found, the OAuth device flow will be initiated.

## Troubleshooting

### "Copilot not authenticated"

Run `/gh-login` or restart with `clanker --copilot` to trigger authentication.

### "github-copilot-sdk not installed"

Install the SDK:
```bash
pip install github-copilot-sdk
```

### Session not found on restore

Copilot sessions may expire. Start a new session with `/clear`.

### Model not available

Your GitHub Copilot subscription may not include all models. Check available models with `/model`.

## MCP Server Support

Copilot mode fully supports MCP servers configured in your `config.yaml`. MCP tools are discovered at startup and integrated natively with the Copilot SDK.

### How It Works

1. **Startup Discovery**: When Copilot mode starts, it queries all configured MCP servers to discover available tools
2. **Tool Whitelisting**: Only clanker's built-in tools and MCP tools are available to the model - Copilot's default built-in tools (like `rg`, `docs-scan`, `web_fetch`) are blocked
3. **Native Integration**: MCP servers run through the Copilot SDK's native MCP support

### Tool Naming

In Copilot mode, MCP tools are named as `{server}-{tool}`:

```
> context7-resolve-library-id: pydantic
> filesystem-read_file: /path/to/file.txt
```

### Configuration

MCP servers are configured the same way for both modes. See [MCP Servers](mcp.md) for details.

```yaml
mcp:
  enabled: true
  servers:
    context7:
      transport: stdio
      command: npx
      args: ["-y", "@anthropic/context7-mcp"]
```
