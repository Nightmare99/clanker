# Available Tools

The agent has access to these built-in tools:

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents with line numbers |
| `write_file` | Create or overwrite files |
| `append_file` | Append content to files |
| `edit_file` | Make targeted string replacements |
| `list_directory` | List directory contents |
| `execute_shell` | Execute shell commands |
| `glob_search` | Find files by pattern |
| `grep_search` | Search file contents with regex |
| `web_search` | Search the web via DuckDuckGo |
| `web_read` | Extract clean content from a web page |

## Tool Details

### read_file

Reads a file and returns its contents with line numbers.

### write_file

Creates a new file or overwrites an existing file with the provided content.

### append_file

Appends content to the end of an existing file.

### edit_file

Makes precise string replacements in a file. Useful for targeted edits without rewriting the entire file.

### list_directory

Lists files and directories at a given path.

### execute_shell

Executes shell commands in a sandboxed environment. Dangerous commands are blocked by default.

### glob_search

Finds files matching a glob pattern (e.g., `**/*.py`, `src/**/*.js`).

### grep_search

Searches file contents using regular expressions. Returns matching lines with context.

### web_search

Searches the web using DuckDuckGo. No API key required.

**Parameters:**
- `query` — Search query string. Be specific for best results.
- `max_results` — Number of results to return (1–10, default 5).

**Returns:** Titles, URLs, and content snippets for each result.

**Example usage by the agent:**
```
web_search("python asyncio gather exception handling", max_results=3)
```

### web_read

Fetches a web page and extracts the main content as clean text, stripping navigation, ads, scripts, and boilerplate HTML.

**Parameters:**
- `url` — The URL to read (must start with `http://` or `https://`).
- `max_length` — Maximum characters to return (1000–50000, default 20000).

**Returns:** Clean extracted text content from the page.

**Notes:**
- Uses browser-like headers to avoid bot detection on most sites.
- Falls back to an alternative fetcher if the primary method fails.
- Some sites with aggressive anti-bot protection (Cloudflare JS challenges) cannot be read. The tool will return an HTTP error code in those cases.

**Example workflow:**
```
web_search("fastapi middleware order")  → finds relevant docs page
web_read("https://fastapi.tiangolo.com/advanced/middleware/")  → reads full content
```

## Web Search Configuration

Web search is enabled by default. To disable it, add to `~/.clanker/config.yaml`:

```yaml
web_search:
  enabled: false
```

When disabled, `web_search` and `web_read` are removed from the agent entirely (no wasted prompt tokens).

## MCP Tools

Additional tools can be loaded from [MCP servers](mcp.md). These appear with a server prefix:

```
[filesystem] read_file
[github] create_issue
```
