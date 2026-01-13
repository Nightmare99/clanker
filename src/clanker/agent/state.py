"""Agent state definitions."""

import operator
from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import NotRequired, TypedDict


class AgentState(TypedDict):
    """State schema for the Clanker agent.

    Attributes:
        messages: Conversation history with automatic message accumulation.
        working_directory: Current working directory for file operations.
        tool_calls_count: Number of tool calls made in current turn.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    working_directory: str
    tool_calls_count: NotRequired[int]
