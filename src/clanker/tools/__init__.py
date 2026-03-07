"""Tool definitions for Clanker agent."""

from clanker.tools.bash_tools import bash
from clanker.tools.file_tools import (
    append_file,
    edit_file,
    list_directory,
    read_file,
    read_project_instructions,
    write_file,
)
from clanker.tools.memory_tools import forget, list_memories, recall, remember
from clanker.tools.search_tools import glob_search, grep_search

# All available tools
ALL_TOOLS = [
    read_project_instructions,
    read_file,
    write_file,
    append_file,
    edit_file,
    list_directory,
    bash,
    glob_search,
    grep_search,
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
    "bash",
    "glob_search",
    "grep_search",
    "remember",
    "recall",
    "forget",
    "list_memories",
]
