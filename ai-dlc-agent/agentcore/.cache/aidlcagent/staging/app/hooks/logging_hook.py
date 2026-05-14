"""Hook: structured logging of tool calls before and after execution."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from strands.hooks import (
    AfterToolCallEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
)

if TYPE_CHECKING:
    from app.observability.logger import StructuredLogger


class ToolCallLoggingHook(HookProvider):
    """
    Logs every tool call before and after execution to a StructuredLogger.

    Attributes:
        agent_name: Name of the agent this hook is attached to.
        logger: StructuredLogger instance for writing JSONL entries.
    """

    def __init__(self, agent_name: str, logger: "StructuredLogger") -> None:
        self.agent_name = agent_name
        self.logger = logger
        self._start_times: dict[str, float] = {}

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Register before and after tool call callbacks."""
        registry.add_callback(BeforeToolCallEvent, self._before_tool)
        registry.add_callback(AfterToolCallEvent, self._after_tool)

    def _before_tool(self, event: BeforeToolCallEvent) -> None:
        """Log tool name, input arguments, and UTC timestamp before execution."""
        tool_use_id = event.tool_use.get("toolUseId", "unknown")
        tool_name = event.tool_use.get("name", "unknown")
        input_args = event.tool_use.get("input", {})

        self._start_times[tool_use_id] = time.monotonic()

        self.logger.log({
            "type": "tool_before",
            "agent_name": self.agent_name,
            "tool_name": tool_name,
            "input_args": input_args,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def _after_tool(self, event: AfterToolCallEvent) -> None:
        """Log tool name, output summary, duration_ms, and UTC timestamp after execution."""
        tool_use_id = event.tool_use.get("toolUseId", "unknown")
        tool_name = event.tool_use.get("name", "unknown")

        start = self._start_times.pop(tool_use_id, time.monotonic())
        duration_ms = (time.monotonic() - start) * 1000

        # Summarize output — truncate to 200 chars to avoid bloating logs
        raw_output = event.tool_result if hasattr(event, "tool_result") else ""
        output_summary = str(raw_output)[:200] if raw_output else ""

        status = "error" if (hasattr(event, "error") and event.error) else "success"

        self.logger.log({
            "type": "tool_after",
            "agent_name": self.agent_name,
            "tool_name": tool_name,
            "output_summary": output_summary,
            "duration_ms": round(duration_ms, 2),
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
