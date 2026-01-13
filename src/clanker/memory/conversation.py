"""Conversation history management."""

from collections.abc import Iterator

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage


class ConversationManager:
    """Manage conversation history with optional summarization."""

    def __init__(self, max_messages: int = 100):
        """Initialize the conversation manager.

        Args:
            max_messages: Maximum number of messages to retain.
        """
        self._messages: list[BaseMessage] = []
        self._max_messages = max_messages

    @property
    def messages(self) -> list[BaseMessage]:
        """Get all messages in the conversation."""
        return self._messages.copy()

    def add_user_message(self, content: str) -> HumanMessage:
        """Add a user message to the conversation.

        Args:
            content: The message content.

        Returns:
            The created message.
        """
        message = HumanMessage(content=content)
        self._add_message(message)
        return message

    def add_assistant_message(self, content: str) -> AIMessage:
        """Add an assistant message to the conversation.

        Args:
            content: The message content.

        Returns:
            The created message.
        """
        message = AIMessage(content=content)
        self._add_message(message)
        return message

    def add_system_message(self, content: str) -> SystemMessage:
        """Add a system message to the conversation.

        Args:
            content: The message content.

        Returns:
            The created message.
        """
        message = SystemMessage(content=content)
        self._add_message(message)
        return message

    def _add_message(self, message: BaseMessage) -> None:
        """Add a message and enforce the limit."""
        self._messages.append(message)
        self._enforce_limit()

    def _enforce_limit(self) -> None:
        """Trim messages if over the limit, preserving system messages."""
        if len(self._messages) <= self._max_messages:
            return

        # Keep system messages and trim oldest non-system messages
        system_messages = [m for m in self._messages if isinstance(m, SystemMessage)]
        other_messages = [m for m in self._messages if not isinstance(m, SystemMessage)]

        # Calculate how many to keep
        keep_count = self._max_messages - len(system_messages)
        if keep_count > 0:
            other_messages = other_messages[-keep_count:]

        self._messages = system_messages + other_messages

    def clear(self) -> None:
        """Clear all messages."""
        self._messages.clear()

    def get_recent(self, n: int = 10) -> list[BaseMessage]:
        """Get the most recent n messages.

        Args:
            n: Number of messages to return.

        Returns:
            List of recent messages.
        """
        return self._messages[-n:]

    def __len__(self) -> int:
        """Return the number of messages."""
        return len(self._messages)

    def __iter__(self) -> Iterator[BaseMessage]:
        """Iterate over messages."""
        return iter(self._messages)
