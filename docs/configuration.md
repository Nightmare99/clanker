# Configuration

Clanker can be configured via config file, web UI, or environment variables.

## Config File

Create a config file at `~/.clanker/config.yaml`:

```yaml
model:
  provider: azure  # or: anthropic, openai, github_copilot
  name: gpt-4o
  temperature: 0.7

  # Azure-specific settings
  azure:
    deployment_name: your-deployment-name
    api_version: "2024-02-15-preview"

  # GitHub Copilot settings (optional model override)
  github_copilot:
    model: null  # Leave null for default, or specify: gpt-4o, claude-sonnet-4

safety:
  require_confirmation: true
  sandbox_commands: true

output:
  syntax_highlighting: true
  show_tool_calls: true
  stream_responses: true
```

## Web Configuration UI

Clanker includes a browser-based configuration interface.

```bash
# Open the configuration UI in your default browser
clanker config

# Use a custom port
clanker config --port 9000

# Start server without opening browser
clanker config --no-browser
```

The web UI provides:

- **Model Settings**: Configure provider, model name, temperature, and max tokens
- **Extended Thinking**: Enable and configure thinking budget for Claude models
- **MCP Server Management**: Add, edit, delete, and test MCP server connections
- **Output Settings**: Toggle tool call display, token usage, and syntax highlighting
- **Safety Settings**: Configure confirmation prompts and command sandboxing
- **Logging Configuration**: Set log levels, file rotation, and console output

All changes are saved to `~/.clanker/config.yaml` and take effect on the next session.

## Environment Variables

```bash
# Azure OpenAI
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=your-deployment

# Anthropic
ANTHROPIC_API_KEY=your-key

# OpenAI
OPENAI_API_KEY=your-key

# GitHub Copilot (obtained via `clanker login`)
GITHUB_TOKEN=your-token

# Override config via environment
CLANKER_MODEL__PROVIDER=azure
CLANKER_MODEL__NAME=gpt-4o
CLANKER_MODEL__AZURE__API_VERSION=2024-02-15-preview
```

## Provider Reference

| Provider | Environment Variables | Example Model |
|----------|----------------------|---------------|
| `azure` | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME` | gpt-4o |
| `anthropic` | `ANTHROPIC_API_KEY` | claude-sonnet-4-20250514 |
| `openai` | `OPENAI_API_KEY` | gpt-4o |
| `github_copilot` | `GITHUB_TOKEN` (via `clanker login`) | gpt-4o, claude-sonnet-4 |

## GitHub Copilot Setup

GitHub Copilot provides access to multiple AI models through your Copilot subscription.

### Authentication

```bash
# Authenticate with GitHub (opens browser)
clanker login

# Remove stored token
clanker logout
```

### Usage

```bash
# Use GitHub Copilot as the provider
clanker --provider github_copilot

# Or set in config.yaml
model:
  provider: github_copilot
```

### Available Models

Depending on your Copilot subscription, you may have access to:
- GPT-4o
- Claude Sonnet 4
- Claude Opus 4
- And more (varies by subscription tier)

Leave the model setting empty to use Copilot's default model.
