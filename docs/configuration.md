# Configuration

Clanker can be configured via config file, web UI, or environment variables.

## Models Configuration (Recommended)

The recommended way to configure LLM providers is using the JSON-based models config at `~/.clanker/models.json`. This allows you to:

- Configure multiple models with different providers
- Switch between models easily with the `/model` command
- Store API keys and connection settings per model
- Enable extended thinking for Anthropic models

### Example models.json

```json
{
  "models": [
    {
      "name": "Claude Sonnet",
      "provider": "Anthropic",
      "model": "claude-sonnet-4-20250514",
      "api_key": null,
      "thinking_enabled": true,
      "thinking_budget_tokens": 10000,
      "max_tokens": 30000
    },
    {
      "name": "GPT-4o",
      "provider": "AzureOpenAI",
      "deployment_name": "gpt-4o",
      "base_url": "https://your-resource.openai.azure.com",
      "api_key": null,
      "api_version": "2024-10-21"
    },
    {
      "name": "GPT-4o (OpenAI)",
      "provider": "OpenAI",
      "model": "gpt-4o",
      "api_key": null
    },
    {
      "name": "Llama Local",
      "provider": "Ollama",
      "model": "llama3",
      "base_url": "http://localhost:11434"
    }
  ],
  "default": "Claude Sonnet"
}
```

### Model Configuration Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Display name for the model (used with `/model` command) |
| `provider` | Yes | One of: `OpenAI`, `AzureOpenAI`, `Anthropic`, `Ollama` |
| `model` | No | Model identifier (e.g., `gpt-4o`, `claude-sonnet-4-20250514`) |
| `api_key` | No | API key (leave null to use environment variable) |
| `base_url` | No | Custom API endpoint |
| `max_tokens` | No | Maximum tokens for response |
| `deployment_name` | No | Azure deployment name (AzureOpenAI only) |
| `api_version` | No | Azure API version (AzureOpenAI only) |
| `thinking_enabled` | No | Enable extended thinking (Anthropic only) |
| `thinking_budget_tokens` | No | Token budget for thinking (default: 10000) |

### Switching Models

Use the `/model` command in interactive mode:

```
❯ /model              # List available models
❯ /model Claude       # Switch to Claude model
❯ /model GPT-4o       # Switch to GPT-4o
```

The current model is shown on startup.

## Legacy Config File

You can also use `~/.clanker/config.yaml` for configuration. If no models are configured in `models.json`, Clanker falls back to this file:

```yaml
model:
  provider: azure  # or: anthropic, openai
  name: gpt-4o
  temperature: 0.7

  # Azure-specific settings
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

- **Models Management**: Add, edit, delete, and test model configurations
- **Extended Thinking**: Enable and configure thinking budget for Claude models
- **Max Tokens**: Configure token limits per model
- **Set Default Model**: Choose which model to use by default
- **MCP Server Management**: Add, edit, delete, and test MCP server connections
- **Output Settings**: Toggle tool call display, token usage, and syntax highlighting
- **Safety Settings**: Configure confirmation prompts and command sandboxing
- **Logging Configuration**: Set log levels, file rotation, and console output

Models are saved to `~/.clanker/models.json`, other settings to `~/.clanker/config.yaml`.

## Extended Thinking (Anthropic)

Extended thinking allows Claude models to reason through complex problems before responding. When enabled, you'll see a "Thinking..." indicator while the model processes.

Configure via `models.json`:

```json
{
  "name": "Claude with Thinking",
  "provider": "Anthropic",
  "model": "claude-sonnet-4-20250514",
  "thinking_enabled": true,
  "thinking_budget_tokens": 10000,
  "max_tokens": 30000
}
```

**Important**: When thinking is enabled, `max_tokens` must be greater than `thinking_budget_tokens`. If not specified, `max_tokens` defaults to `thinking_budget_tokens + 16000`.

## Environment Variables

API keys can be set via environment variables instead of storing them in config files:

```bash
# Azure OpenAI
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=your-deployment

# Anthropic
ANTHROPIC_API_KEY=your-key

# OpenAI
OPENAI_API_KEY=your-key
```

When a model in `models.json` has `api_key: null`, Clanker will automatically use the corresponding environment variable.

## Provider Reference

| Provider | Environment Variables | Example Model |
|----------|----------------------|---------------|
| `AzureOpenAI` | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT` | gpt-4o |
| `Anthropic` | `ANTHROPIC_API_KEY` | claude-sonnet-4-20250514 |
| `OpenAI` | `OPENAI_API_KEY` | gpt-4o |
| `Ollama` | None (local) | llama3, mistral |
