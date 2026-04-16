"""Tool definitions for Clanker agent."""

from clanker.tools.bash_tools import run
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

# All available tools
ALL_TOOLS = [
    read_project_instructions,
    read_file,
    write_file,
    append_file,
    edit_file,
    list_directory,
    run,
    glob_search,
    grep_search,
    # Communication tools
    notify,
    # Memory tools
    remember,
    recall,
    forget,
    list_memories,
]

__all__ = [
    "ALL_TOOLS",
    "read_project_instructions",
    "read_file",
    "write_file",
    "append_file",
    "edit_file",
    "list_directory",
    "run",
    "glob_search",
    "grep_search",
    "notify",
    "remember",
    "recall",
    "forget",
    "list_memories",
]
