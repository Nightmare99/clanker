"""Token usage tracking and context window management."""

from dataclasses import dataclass, field

# Context window sizes for common models (in tokens)
# These are approximate and may change with model updates
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # Anthropic models
    "claude-3-opus": 200_000,
    "claude-3-sonnet": 200_000,
    "claude-3-haiku": 200_000,
    "claude-3-5-sonnet": 200_000,
    "claude-3-5-haiku": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-sonnet-4-5": 200_000,
    "claude-opus-4": 200_000,
    # OpenAI models
    "gpt-4": 8_192,
    "gpt-4-32k": 32_768,
    "gpt-4-turbo": 128_000,
    "gpt-4-turbo-preview": 128_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4.1": 1_000_000,
    "gpt-3.5-turbo": 16_385,
    "gpt-3.5-turbo-16k": 16_385,
    # o-series (reasoning models)
    "o1": 200_000,
    "o1-preview": 128_000,
    "o1-mini": 128_000,
    "o3": 200_000,
    "o3-mini": 200_000,
    "o4-mini": 200_000,
}

# Default context window for unknown models
DEFAULT_CONTEXT_WINDOW = 128_000


def get_context_window(model_name: str) -> int:
    """Get the context window size for a model.

    Args:
        model_name: The model name/identifier.

    Returns:
        Context window size in tokens.
    """
    # Exact match first
    if model_name in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model_name]

    # Try prefix matching (for versioned models like claude-3-5-sonnet-20241022)
    model_lower = model_name.lower()
    for key, value in MODEL_CONTEXT_WINDOWS.items():
        if model_lower.startswith(key.lower()):
            return value

    # Check for common patterns
    if "claude" in model_lower:
        return 200_000
    if "gpt-4" in model_lower:
        return 128_000
    if "gpt-3" in model_lower:
        return 16_385

    return DEFAULT_CONTEXT_WINDOW


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

    # Context window info
    context_window: int = DEFAULT_CONTEXT_WINDOW

    @property
    def context_used_percent(self) -> float:
        """Calculate percentage of context window used."""
        if self.context_window <= 0:
            return 0.0
        return (self.cumulative_total / self.context_window) * 100

    @property
    def context_remaining_percent(self) -> float:
        """Calculate percentage of context window remaining."""
        return max(0.0, 100.0 - self.context_used_percent)

    @property
    def context_remaining_tokens(self) -> int:
        """Calculate tokens remaining in context window."""
        return max(0, self.context_window - self.cumulative_total)


@dataclass
class SessionTokenTracker:
    """Track token usage across an entire session."""

    model_name: str = ""
    context_window: int = DEFAULT_CONTEXT_WINDOW

    # Per-turn tracking
    turns: list[TokenUsage] = field(default_factory=list)

    # Current context size (last input tokens = full conversation context)
    # Note: input_tokens from LLM includes entire conversation history
    current_context_tokens: int = 0

    # Cumulative output tokens (for cost tracking)
    total_output: int = 0

    def __post_init__(self):
        if self.model_name:
            self.context_window = get_context_window(self.model_name)

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
    def context_used_percent(self) -> float:
        """Calculate percentage of context window used.

        Based on current context size (last turn's input + output),
        not cumulative totals which would double-count.
        """
        if self.context_window <= 0:
            return 0.0
        return (self.current_context_tokens / self.context_window) * 100

    @property
    def context_remaining_percent(self) -> float:
        """Calculate percentage of context window remaining."""
        return max(0.0, 100.0 - self.context_used_percent)
