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

## MCP Tools

Additional tools can be loaded from [MCP servers](mcp.md). These appear with a server prefix:

```
[filesystem] read_file
[github] create_issue
```
