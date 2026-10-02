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

## Slow Conversation Compaction

A large imported conversation can take multiple summary calls when first
continued. Check `~/.clanker/logs/clanker.log` for `Summarizing ... chunk(s)`
and `Compaction progress` entries to see how much work remains. `/compact`
runs asynchronously in the TUI and displays chunk progress; Ctrl+C cancels it.

If the TUI completely freezes or the same full imported history is summarized
again after a completed compaction, update Clanker. Older versions invoked
manual compaction on the UI thread and generated a second summary to sync
the display transcript. Current versions reuse the completed checkpoint
summary and clear pending import/restore replay after manual compaction.

## ChatGPT (OpenAI) Login

- **Not connected / expired login:** Run `clanker openai-login` or reconnect
  through the ChatGPT account card. Temporary refresh failures keep the login
  for retry; revoked/invalid refresh tokens require signing in again.
- **Port 1455 occupied:** Close other Codex/OpenAI login attempts, or use
  `clanker openai-login --no-browser --manual`. This registered redirect cannot
  move to an arbitrary port. The web UI offers **Remote / headless login**.
- **Remote browser cannot load localhost:** After authorizing, copy the full
  callback URL into the hidden CLI prompt or web callback field.
- **State mismatch / expired callback:** Use the current attempt's login link
  and full callback URL. Login expires after ten minutes; start a fresh attempt.
- **No models / HTTP 401 or 403:** Reconnect and check the account's Codex access.
  Refresh Models uses your account's current catalogue, not the public API list.
- **HTTP 429:** Account usage limits still apply; wait and retry.
- **Stream ends before completion:** Retry after checking the network. Increase
  `stream_chunk_timeout` for long reasoning pauses, or set it to `0` to disable.

See [ChatGPT configuration](configuration.md#chatgpt-openai-account) for details.

## Google Antigravity Login

- **Fractional token limits / missing model profile**: Update Clanker and restart
  the session. Documented Antigravity models now receive context defaults even
  from previously saved configuration. Models with unknown limits use an
  absolute compaction budget; optionally set `max_input_tokens` to a known
  limit in the model editor. See [Antigravity configuration](configuration.md#google-antigravity).

- **Browser does not open:** Open the displayed Google authorization link
  manually, or run `clanker antigravity-login --no-browser`.
- **SSH/remote callback cannot load:** Run
  `clanker antigravity-login --no-browser --manual`. Open the link locally,
  grant access, and paste the full callback URL (including `code` and `state`)
  into the hidden terminal prompt. The web UI offers **Use callback URL** too.
- **Callback ports unavailable:** Close other Google login attempts and retry.
  Clanker tries ports 51121–51126, including fallbacks for Windows port reservations.
- **State mismatch or expired login:** Start a fresh login and use only that
  attempt's link and callback URL. Login expires after ten minutes.
- **Revoked login:** Reconnect through `clanker antigravity-login` or the web
  account card. Temporary token-refresh failures retain your login for retry.
- **HTTP 403, no project, or no supported models:** Check Google account
  eligibility and Antigravity access. This unofficial API may be restricted;
  see [the integration notes](configuration.md#google-antigravity).
- **HTTP 429:** Check your account quota and retry later.

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
