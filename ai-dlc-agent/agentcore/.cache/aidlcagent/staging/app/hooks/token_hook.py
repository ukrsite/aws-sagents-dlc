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
    """

    def __init__(self) -> None:
        self.input_tokens: int = 0
        self.output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Total tokens consumed (input + output)."""
        return self.input_tokens + self.output_tokens

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Register after-model-call callback for token counting."""
        registry.add_callback(AfterModelCallEvent, self._count_tokens)

    def _count_tokens(self, event: AfterModelCallEvent) -> None:
        """Increment session-level input/output token counters from event usage metadata."""
        # The Strands SDK exposes usage via event.response or event.stop_response
        usage = None
        if hasattr(event, "response") and event.response:
            usage = getattr(event.response, "usage", None)
        if usage is None and hasattr(event, "stop_response") and event.stop_response:
            usage = getattr(event.stop_response, "usage", None)

        if usage is not None:
            self.input_tokens += getattr(usage, "inputTokens", 0) or getattr(usage, "input_tokens", 0)
            self.output_tokens += getattr(usage, "outputTokens", 0) or getattr(usage, "output_tokens", 0)
