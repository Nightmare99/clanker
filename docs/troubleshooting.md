# Troubleshooting

## Azure OpenAI Issues

### "AZURE_OPENAI_API_KEY not set"

- Ensure your `.env` file exists and contains `AZURE_OPENAI_API_KEY`
- Or export it: `export AZURE_OPENAI_API_KEY=your-key`

### "AZURE_OPENAI_ENDPOINT not set"

- Add your Azure endpoint: `AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/`

### "Azure deployment name not set"

- Set `AZURE_OPENAI_DEPLOYMENT_NAME` in your environment
- Or configure `model.azure.deployment_name` in your config file

### Finding Your Azure OpenAI Details

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to your Azure OpenAI resource
3. Find **Keys and Endpoint** for your API key and endpoint
4. Go to **Model deployments** to find your deployment name

## Anthropic Issues

### "ANTHROPIC_API_KEY not set"

- Set your API key: `export ANTHROPIC_API_KEY=your-key`
- Or add it to your `.env` file

## MCP Server Issues

### Server not loading

1. Check the command path is correct
2. Ensure the server is installed (`npx`, `python`, etc.)
3. Verify environment variables are set correctly
4. Use `/mcp` to see server status
5. Check `/logs` for detailed error messages

### Tools not working

- MCP tools require async execution - ensure you're using the latest version
- Test the server connection via `clanker config` web UI

## GitHub Copilot Issues

### "github-copilot-sdk not installed"

Install the Copilot SDK:
```bash
pip install github-copilot-sdk
```

### "Copilot not authenticated" / "No Copilot token found"

Authenticate with GitHub:
```bash
# Option 1: Start with --copilot (will prompt automatically)
clanker --copilot

# Option 2: Run /gh-login from any session
❯ /gh-login
```

### Token expired

Copilot tokens expire after ~8 hours. Re-authenticate:
```bash
❯ /gh-login
```

### Model not available

Your GitHub Copilot subscription may not include all models. Check available models:
```
❯ /model
```

### Session not found on restore

Copilot sessions may expire or be cleaned up by the SDK. Start a new session with `/clear`.

### Can't switch between BYOK and Copilot

Modes are mutually exclusive. You must exit and restart with the appropriate flag:
```bash
clanker           # BYOK mode
clanker --copilot # Copilot mode
```

### Web config UI doesn't show Copilot settings

The web configuration UI (`clanker config`) only manages BYOK mode settings. Copilot mode uses GitHub's infrastructure and doesn't require local configuration.

### MCP tools not working in Copilot mode

MCP servers are discovered at startup in Copilot mode. If tools aren't working:

1. Ensure `mcp.enabled: true` in `~/.clanker/config.yaml`
2. Check server configuration is correct (transport, command/url)
3. Restart clanker to trigger MCP tool discovery
4. Check logs with `/logs` for discovery errors

**Note**: Copilot mode blocks Copilot's built-in tools (like `rg`, `docs-scan`, `web_fetch`) and only allows clanker's tools plus your configured MCP tools.

### Seeing Copilot built-in tools instead of clanker's

If you see tools like `rg`, `docs-scan`, or `report_intent` being invoked, this indicates tool isolation isn't working correctly. This is typically a configuration issue - ensure MCP servers are properly configured so the tool whitelist can be built correctly.

## General Issues

### Conversation not persisting

- **BYOK mode**: Conversations are stored in `.clanker/conversations/` in your working directory
- **Copilot mode**: Sessions are stored in `~/.copilot/session-state/` by the SDK
- Check that the directories exist and are writable

### High memory usage

- Long conversations accumulate context; use `/clear` to reset
- **BYOK mode**: Summarization kicks in at the configured threshold (default 80%)
- **Copilot mode**: SDK handles infinite sessions with automatic compaction

### Logs not appearing

- Ensure logging is enabled in config: `logging.enabled: true`
- Check the log directory exists: `~/.clanker/logs/`
