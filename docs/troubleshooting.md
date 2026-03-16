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

## GitHub Copilot Issues

### "GitHub token not set"

1. Run `clanker login` to authenticate
2. Follow the prompts to visit GitHub and enter the code
3. Once authenticated, try again

### "Authentication timed out"

- The device code expires after 15 minutes
- Run `clanker login` again to get a new code

### Token expired

GitHub Copilot tokens are long-lived but may eventually expire:
1. Run `clanker logout` to clear the old token
2. Run `clanker login` to re-authenticate

### Model not available

- Some models require specific Copilot subscription tiers (Pro, Pro+, Business, Enterprise)
- Leave the model setting empty to use the default model for your subscription

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

## General Issues

### Conversation not persisting

- Check that `~/.clanker/` directory exists and is writable
- Conversations are stored in `.clanker/conversations/` in your working directory

### High memory usage

- Long conversations accumulate context; use `/clear` to reset
- Context compaction kicks in automatically at 70% usage

### Logs not appearing

- Ensure logging is enabled in config: `logging.enabled: true`
- Check the log directory exists: `~/.clanker/logs/`
