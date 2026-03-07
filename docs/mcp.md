# MCP Servers

Clanker supports [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) servers, allowing you to extend the agent with external tools.

## Configuration

Add MCP servers to your `~/.clanker/config.yaml`:

```yaml
mcp:
  enabled: true
  servers:
    # Filesystem server (stdio transport)
    filesystem:
      transport: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/dir"]

    # Custom server with environment variables
    my-server:
      transport: stdio
      command: python
      args: ["/path/to/my_mcp_server.py"]
      env:
        API_KEY: "your-api-key"

    # SSE transport (for remote servers)
    remote-api:
      transport: sse
      url: http://localhost:8000/mcp/sse
```

You can also manage MCP servers via the [web configuration UI](configuration.md#web-configuration-ui).

## Supported Transports

| Transport | Description |
|-----------|-------------|
| `stdio` | Launches server as subprocess, communicates via stdin/stdout |
| `sse` | Connects to server via Server-Sent Events (HTTP) |

## Tool Display

MCP tools are displayed with their server name prefix:

```
  > [filesystem] read_file: /path/to/file.txt
  > [my-server] custom_tool: query
```

## Testing Connections

Use the web configuration UI to test MCP server connections before saving. The test button verifies the server can be reached and responds correctly.

## Popular MCP Servers

- `@modelcontextprotocol/server-filesystem` - File system access
- `@modelcontextprotocol/server-github` - GitHub integration
- `@modelcontextprotocol/server-postgres` - PostgreSQL database
- `@modelcontextprotocol/server-slack` - Slack integration

## Troubleshooting

**Server not loading?**
- Check the command path is correct
- Ensure required environment variables are set
- Use `/mcp` command to see server status
- Check logs with `/logs` for error details
