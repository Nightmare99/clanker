"""Settings management using Pydantic."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SafetySettings(BaseModel):
    """Safety and security configuration."""

    require_confirmation: bool = True
    sandbox_commands: bool = True
    max_file_size: int = Field(default=1_000_000, gt=0)  # 1MB
    command_timeout: int = Field(default=120_000, gt=0)  # 2 minutes in ms
    # Seconds before a foreground `execute_shell` command is auto-promoted
    # to a background job (returns immediately with a job id so the agent
    # can keep working). Set to 0 to disable auto-promotion.
    foreground_promote_after_seconds: int = Field(default=30, ge=0)
    # User-defined command blacklist (system-wide). Any command containing one
    # of these entries as a case-insensitive substring is blocked at the
    # sandbox gate, in addition to the built-in blocked commands, and unioned
    # with the project-specific `.clanker/blacklist` file. Only enforced when
    # `sandbox_commands` is enabled.
    command_blacklist: list[str] = Field(default_factory=list)


class OutputSettings(BaseModel):
    """Output formatting configuration."""

    syntax_highlighting: bool = True
    show_tool_calls: bool = True
    stream_responses: bool = True
    show_token_usage: bool = True


class ContextSettings(BaseModel):
    """Context management configuration."""

    # Number of recent conversation turns to keep after summarization
    keep_recent_turns: int = Field(default=4, ge=1, le=20)
    # Percentage of context window to trigger summarization (0-100)
    summarization_threshold: float = Field(default=80.0, ge=50.0, le=99.0)
    # Maximum tokens of any single tool result kept in the conversation.
    # Oversized results are head/tail truncated at the tool boundary so one
    # large output cannot overflow the context window. 0 disables truncation.
    max_tool_result_tokens: int = Field(default=20_000, ge=0)
    # Maximum tokens of any single tool-call ARGUMENT string (e.g. write_file
    # `content`, edit_file old_string/new_string) sent back to the model.
    # Oversized args are head/tail truncated on the request path so accumulated
    # large writes cannot bloat the request past a provider's size limit (a
    # common cause of HTTP 413 on proxy/gateway endpoints). 0 disables.
    max_tool_call_arg_tokens: int = Field(default=4_000, ge=0)
    # Maximum agent loop steps (LangGraph super-steps) per turn before the
    # turn is stopped. Each model call + tool round-trip is one step; large
    # multi-file lint/test loops can legitimately use many. Hitting the limit
    # ends the turn gracefully rather than crashing.
    max_agent_steps: int = Field(default=1000, ge=10, le=10_000)


class MemorySettings(BaseModel):
    """Memory and persistence configuration."""

    persist_sessions: bool = True
    max_history_length: int = Field(default=100, gt=0)
    storage_path: Path = Path.home() / ".clanker" / "sessions"


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server."""

    transport: Literal["stdio", "sse"] = "stdio"
    # For stdio transport
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    # For SSE transport
    url: str | None = None
    # Whether this server is enabled
    enabled: bool = True


class MCPSettings(BaseModel):
    """MCP (Model Context Protocol) settings."""

    enabled: bool = True
    servers: dict[str, MCPServerConfig] = Field(default_factory=dict)


class LoggingSettings(BaseModel):
    """Logging configuration."""

    enabled: bool = True
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_dir: Path = Path.home() / ".clanker" / "logs"
    max_file_size_mb: int = Field(default=5, gt=0)  # 5 MB per file
    backup_count: int = Field(default=3, ge=1, le=10)  # Keep 3 backup files
    console_output: bool = False  # Also log to console (for debugging)
    detailed_format: bool = True  # Include function/line info in logs


class WebSearchSettings(BaseModel):
    """Web search configuration."""

    enabled: bool = True


class AgentSettings(BaseModel):
    """Agent identity settings."""

    name: str = "Clanker"


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_prefix="CLANKER_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # Nested settings
    agent: AgentSettings = Field(default_factory=AgentSettings)
    safety: SafetySettings = Field(default_factory=SafetySettings)
    output: OutputSettings = Field(default_factory=OutputSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    context: ContextSettings = Field(default_factory=ContextSettings)
    mcp: MCPSettings = Field(default_factory=MCPSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    web_search: WebSearchSettings = Field(default_factory=WebSearchSettings)

    @classmethod
    def from_yaml(cls, path: Path, create_default: bool = True) -> "Settings":
        """Load settings from a YAML file.

        Args:
            path: Path to the YAML config file.
            create_default: If True, create a default config if file doesn't exist.

        Returns:
            Settings instance.
        """
        if not path.exists():
            settings = cls()
            if create_default:
                settings.save_yaml_with_comments(path)
            return settings

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        return cls(**data)

    def save_yaml(self, path: Path) -> None:
        """Save settings to a YAML file."""
        path.parent.mkdir(parents=True, exist_ok=True)

        data = self.model_dump(exclude_none=True)

        # Convert Path objects to strings for YAML serialization
        def convert_paths(obj):
            if isinstance(obj, dict):
                return {k: convert_paths(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_paths(v) for v in obj]
            elif isinstance(obj, Path):
                return str(obj)
            return obj

        data = convert_paths(data)

        with open(path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False)

    def save_yaml_with_comments(self, path: Path) -> None:
        """Save settings to a YAML file with helpful comments."""
        path.parent.mkdir(parents=True, exist_ok=True)

        config_content = """\
# Clanker Configuration
# https://github.com/yourusername/clanker
#
# Model configuration is stored separately in ~/.clanker/models.json
# Use 'clanker model add' to configure models

# Agent identity
agent:
  # Name used by the assistant across sessions
  name: Clanker

safety:
  require_confirmation: true
  sandbox_commands: true
  max_file_size: 1000000
  command_timeout: 120000
  foreground_promote_after_seconds: 30  # 0 disables auto-promotion to background
  # Commands the agent must never run. Case-insensitive substring match, so
  # "git push" blocks "git push origin main". Applied on top of the built-in
  # blocks and unioned with a project's .clanker/blacklist file. Only enforced
  # while sandbox_commands is true.
  command_blacklist: []
    # - git push
    # - npm publish
    # - terraform apply

output:
  syntax_highlighting: true
  show_tool_calls: true
  stream_responses: true
  show_token_usage: true  # Show token count and context remaining after each response

# Context management (automatic summarization via SummarizationMiddleware)
# When conversation exceeds the threshold % of the model's context window,
# older messages are summarized to free up space
context:
  keep_recent_turns: 4  # Keep last N conversation turns after summarization
  summarization_threshold: 80.0  # Trigger at this % of context window (50-99)
  max_tool_result_tokens: 20000  # Cap any single tool result to this many tokens (0 disables)
  max_tool_call_arg_tokens: 4000  # Cap any single tool-call argument (e.g. file content sent to write_file) to this many tokens (0 disables)
  max_agent_steps: 1000  # Max agent loop steps per turn before stopping gracefully

memory:
  persist_sessions: true
  max_history_length: 100

# MCP (Model Context Protocol) Servers
# Add external tool servers here
mcp:
  enabled: true
  servers: {}
    # Example stdio server:
    # filesystem:
    #   transport: stdio
    #   command: npx
    #   args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
    #
    # Example SSE server:
    # my-api:
    #   transport: sse
    #   url: http://localhost:8000/mcp/sse

# Logging configuration
logging:
  enabled: true
  level: INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL
  max_file_size_mb: 5  # Max size per log file before rotation
  backup_count: 3  # Number of backup files to keep (max 10)
  console_output: false  # Also output logs to console
  detailed_format: true  # Include function/line info in logs
"""
        with open(path, "w") as f:
            f.write(config_content)


# Default config path
CONFIG_PATH = Path.home() / ".clanker" / "config.yaml"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings.from_yaml(CONFIG_PATH)


def reload_settings() -> Settings:
    """Reload settings, clearing the cache."""
    get_settings.cache_clear()
    return get_settings()
