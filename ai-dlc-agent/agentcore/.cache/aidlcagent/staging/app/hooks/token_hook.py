"""Hook: session-level token counting across agent invocations."""

from __future__ import annotations

from typing import Any

from strands.hooks import AfterModelCallEvent, HookProvider, HookRegistry


class TokenCountingHook(HookProvider):
    """
    Counts input and output tokens consumed across all agent invocations.

    Attributes:
        input_tokens: Cumulative input token count.
        output_tokens: Cumulative output token count.
        cache_read_tokens: Cumulative cache read tokens (prompt caching).
        cache_creation_tokens: Cumulative cache creation tokens (prompt caching).
    """

    def __init__(self) -> None:
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.cache_read_tokens: int = 0
        self.cache_creation_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Total tokens consumed (input + output)."""
        return self.input_tokens + self.output_tokens

    @property
    def cache_savings(self) -> int:
        """Tokens saved by prompt caching (cache reads cost 90% less than regular input)."""
        # Cache reads cost 10% of regular input tokens, so we saved 90%
        return int(self.cache_read_tokens * 0.9)

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Register after-model-call callback for token counting."""
        registry.add_callback(AfterModelCallEvent, self._count_tokens)

    def _count_tokens(self, event: AfterModelCallEvent) -> None:
        """Increment session-level input/output token counters from event usage metadata."""
        if not event.stop_response or not event.stop_response.message:
            return

        # Usage data is nested: message["metadata"]["usage"]
        message = event.stop_response.message
        metadata = message.get("metadata", {})
        usage = metadata.get("usage", {})

        if usage:
            self.input_tokens += usage.get("inputTokens", 0)
            self.output_tokens += usage.get("outputTokens", 0)
            # Track prompt caching metrics (Bedrock/Anthropic)
            self.cache_read_tokens += usage.get("cacheReadInputTokens", 0)
            self.cache_creation_tokens += usage.get("cacheCreationInputTokens", 0)
