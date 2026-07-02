"""Token usage tracking and context window management.

The context window is **not** hardcoded or guessed from the model name. It is
supplied by the caller from the user's model config (`ModelConfig.max_input_tokens`).
When that value is unknown (`None`), the context-usage percentages are `None`
and the TUI omits the context portion of the token line rather than showing a
misleading number.
"""

from dataclasses import dataclass, field


@dataclass
class TokenUsage:
    """Track token usage for a conversation turn."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    # Cumulative tracking across the session
    cumulative_input: int = 0
    cumulative_output: int = 0
    cumulative_total: int = 0

    # Context window info. None when the model config does not specify
    # max_input_tokens — in that case usage percentages are unknown.
    context_window: int | None = None

    @property
    def context_used_percent(self) -> float | None:
        """Percentage of context window used, or None if the window is unknown."""
        if not self.context_window or self.context_window <= 0:
            return None
        return (self.cumulative_total / self.context_window) * 100

    @property
    def context_remaining_percent(self) -> float | None:
        """Percentage of context window remaining, or None if unknown."""
        used = self.context_used_percent
        if used is None:
            return None
        return max(0.0, 100.0 - used)

    @property
    def context_remaining_tokens(self) -> int | None:
        """Tokens remaining in the context window, or None if unknown."""
        if not self.context_window or self.context_window <= 0:
            return None
        return max(0, self.context_window - self.cumulative_total)


@dataclass
class SessionTokenTracker:
    """Track token usage across an entire session."""

    model_name: str = ""
    # Supplied by the caller from ModelConfig.max_input_tokens. None means the
    # user has not configured a window, so percentages cannot be computed.
    context_window: int | None = None

    # Per-turn tracking
    turns: list[TokenUsage] = field(default_factory=list)

    # Current context size (last input tokens = full conversation context)
    # Note: input_tokens from LLM includes entire conversation history
    current_context_tokens: int = 0

    # Cumulative output tokens (for cost tracking)
    total_output: int = 0

    def add_turn(self, input_tokens: int, output_tokens: int,
                 cache_read: int = 0, cache_creation: int = 0) -> TokenUsage:
        """Record token usage for a conversation turn.

        Args:
            input_tokens: Tokens from the LAST LLM call in the turn (full context).
                          Each LLM call re-sends the full conversation history so we
                          use only the final call's input to avoid double-counting.
            output_tokens: Total output tokens across all LLM calls in the turn.
            cache_read: Cache-read tokens from the last LLM call (Anthropic).
            cache_creation: Cache-creation tokens from the last LLM call (Anthropic).

        Returns:
            TokenUsage for this turn with cumulative stats.
        """
        # input_tokens is the LAST call's input, which already encodes the full
        # conversation history.  Adding output_tokens gives the context size the
        # model will see on the NEXT turn (history + this response).
        self.current_context_tokens = input_tokens + output_tokens
        self.total_output += output_tokens

        usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_creation,
            cumulative_input=input_tokens,
            cumulative_output=self.total_output,
            cumulative_total=self.current_context_tokens,
            context_window=self.context_window,
        )

        self.turns.append(usage)
        return usage

    @property
    def context_used_percent(self) -> float | None:
        """Percentage of context window used, or None if the window is unknown.

        Based on current context size (last turn's input + output),
        not cumulative totals which would double-count.
        """
        if not self.context_window or self.context_window <= 0:
            return None
        return (self.current_context_tokens / self.context_window) * 100

    @property
    def context_remaining_percent(self) -> float | None:
        """Percentage of context window remaining, or None if unknown."""
        used = self.context_used_percent
        if used is None:
            return None
        return max(0.0, 100.0 - used)
