# Logging

Clanker includes robust logging for traceability and debugging. Logs are stored in `~/.clanker/logs/` with automatic rotation.

## Configuration

Configure logging in `~/.clanker/config.yaml`:

```yaml
logging:
  enabled: true
  level: INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL
  max_file_size_mb: 5  # Max size per log file before rotation
  backup_count: 3  # Number of backup files to keep (max 10)
  console_output: false  # Also output logs to console (for debugging)
  detailed_format: true  # Include function/line info in logs
```

## Log Files

- **Location**: `~/.clanker/logs/clanker.log`
- **Rotation**: When a log file reaches `max_file_size_mb`, it's rotated to `clanker.log.1`, `clanker.log.2`, etc.
- **Retention**: Only `backup_count` backup files are kept (oldest are deleted)

## Viewing Logs

Use the `/logs` command in the interactive session:

```
❯ /logs
Log file: /home/user/.clanker/logs/clanker.log
Log level: INFO
Max file size: 5 MB
Backup count: 3

Log files in /home/user/.clanker/logs:
  clanker.log (12.3 KB)
  clanker.log.1 (5120.0 KB)
```

Or view logs directly:

```bash
# Follow logs in real-time
tail -f ~/.clanker/logs/clanker.log

# View recent entries
tail -100 ~/.clanker/logs/clanker.log
```

## What's Logged

- Session start/stop and configuration
- User messages (truncated for privacy)
- Tool invocations (file reads, writes, edits, bash commands)
- Agent responses and errors
- MCP server connections and tool loading
