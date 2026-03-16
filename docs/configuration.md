# Configuration

Clanker can be configured via config file, web UI, or environment variables.

## Config File

Create a config file at `~/.clanker/config.yaml`:

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
