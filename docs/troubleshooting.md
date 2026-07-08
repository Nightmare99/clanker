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

## General Issues

### Conversation not persisting

- Conversations are stored in `.clanker/conversations/` in your working directory
- Check that the directories exist and are writable

### High memory usage

- Long conversations accumulate context; use `/clear` to reset
- Summarization kicks in at the configured threshold (default 80%)

### Logs not appearing

- Ensure logging is enabled in config: `logging.enabled: true`
- Check the log directory exists: `~/.clanker/logs/`

### "zlib.error: incorrect header check" / "Error -3 while decompressing data"

- This can happen in the pre-built binary release after a bash command runs
  (`execute_shell` / background jobs) and the agent then uses a tool whose
  third-party dependency hadn't been loaded yet (e.g. `web_search`,
  `web_read`, reading a PDF). It's a known PyInstaller quirk: forking a
  subprocess can disturb the frozen binary's on-demand module loader, so the
  *first* import of a not-yet-loaded package can fail right after a fork.
  Which tool trips it depends on call order, which is why it can look random.
- Clanker preloads the packages known to hit this (`ddgs`, `trafilatura`,
  `fitz`/PyMuPDF, `pypdf`, plus Pygments' lexers/styles) at startup, before
  any subprocess can run, specifically to avoid this. If you still hit it —
  e.g. from a newly added tool dependency — simply retrying the same prompt
  works, since the module is now loaded for the rest of the session.

### "Command blocked - Command is blacklisted"

- The command matched an entry in your command blacklist (a case-insensitive
  substring match). This is intentional — it is a safety control.
- System-wide entries live in `safety.command_blacklist` in
  `~/.clanker/config.yaml` (editable in `clanker config` → Safety).
- Project entries live in `.clanker/blacklist` in the current repository (one
  substring per line). The effective list is the union of both.
- The blacklist is only enforced while `safety.sandbox_commands` is `true`.
- See [Configuration → Command Blacklist](configuration.md#command-blacklist)
  for details.

