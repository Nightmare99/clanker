"""Tool definitions for Clanker agent."""

from clanker.tools.background import (
    bash_background,
    bash_kill,
    bash_output,
    bash_status,
    bash_wait,
)
from clanker.tools.bash_tools import execute_shell
from clanker.tools.file_tools import (
    append_file,
    edit_file,
    list_directory,
    read_file,
    read_project_instructions,
    write_file,
)
from clanker.tools.memory_tools import forget, list_memories, recall, remember
from clanker.tools.notify_tools import notify
from clanker.tools.search_tools import glob_search, grep_search
from clanker.tools.web_tools import web_read, web_search

# All available tools
ALL_TOOLS = [
    read_project_instructions,
    read_file,
    write_file,
    append_file,
    edit_file,
    list_directory,
    execute_shell,
    bash_background,
    bash_status,
    bash_output,
    bash_wait,
    bash_kill,
    glob_search,
    grep_search,
    # Communication tools
    notify,
    # Memory tools
    remember,
    recall,
    forget,
    list_memories,
    # Web tools
    web_search,
    web_read,
]


def get_tools() -> list:
    """Get active tools based on configuration.

    Returns all tools, excluding web tools if web_search is disabled in config.
    """
    from clanker.config.settings import get_settings

    settings = get_settings()
    if not settings.web_search.enabled:
        return [t for t in ALL_TOOLS if t not in (web_search, web_read)]
    return list(ALL_TOOLS)


__all__ = [
    "ALL_TOOLS",
    "get_tools",
    "read_project_instructions",
    "read_file",
    "write_file",
    "append_file",
    "edit_file",
    "list_directory",
    "execute_shell",
    "bash_background",
    "bash_status",
    "bash_output",
    "bash_wait",
    "bash_kill",
    "glob_search",
    "grep_search",
    "notify",
    "remember",
    "recall",
    "forget",
    "list_memories",
    "web_search",
    "web_read",
]
