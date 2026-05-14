"""Structured JSON Lines logger for the AI-DLC Strands Agent."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class StructuredLogger:
    """
    Writes structured JSON log entries to a JSONL file (and optionally stdout).

    Each log entry is a JSON object on a single line (JSON Lines format).
    The output directory is created automatically if it does not exist.

    Args:
        log_file: Path to the JSONL output file (default: outputs/agent_trace.jsonl).
        verbose: If True, also print each entry to stdout. Defaults to False.
                 Can be overridden by setting the AIDLC_VERBOSE=1 environment variable.
    """

    def __init__(
        self,
        log_file: str = "outputs/agent_trace.jsonl",
        verbose: bool = False,
    ) -> None:
        self.log_file = log_file
        # Respect AIDLC_VERBOSE env var: "1" or "true" enables stdout output.
        env_verbose = os.environ.get("AIDLC_VERBOSE", "").lower()
        self.verbose = verbose or env_verbose in ("1", "true", "yes")
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    def log(self, entry: dict[str, Any]) -> None:
        """
        Write a JSON entry to the JSONL file (and stdout if verbose).

        Args:
            entry: Dictionary to serialize as a JSON line.
        """
        line = json.dumps(entry, default=str, ensure_ascii=False)
        if self.verbose:
            print(line, flush=True)
        with open(self.log_file, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def log_agent_invocation(
        self,
        agent_name: str,
        input_len: int,
        output_len: int,
        duration_ms: float,
    ) -> None:
        """
        Emit a structured log entry for an agent invocation.

        Args:
            agent_name: Name of the agent (e.g., "inception_agent").
            input_len: Length of the input prompt in characters.
            output_len: Length of the agent response in characters.
            duration_ms: Execution duration in milliseconds.
        """
        self.log({
            "type": "agent_invocation",
            "agent_name": agent_name,
            "input_length": input_len,
            "output_length": output_len,
            "duration_ms": round(duration_ms, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def log_tool_call(
        self,
        agent_name: str,
        tool_name: str,
        input_args: dict[str, Any],
        status: str,
    ) -> None:
        """
        Emit a structured log entry for a tool call.

        Args:
            agent_name: Name of the agent invoking the tool.
            tool_name: Name of the tool being called.
            input_args: Sanitized input arguments (no secrets).
            status: "success" or "error".
        """
        self.log({
            "type": "tool_call",
            "agent_name": agent_name,
            "tool_name": tool_name,
            "input_args": input_args,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def log_retry(
        self,
        operation: str,
        attempt: int,
        reason: str,
    ) -> None:
        """
        Emit a structured log entry for a retry attempt.

        Args:
            operation: Name of the operation being retried.
            attempt: Current attempt number (1-based).
            reason: Reason for the retry.
        """
        self.log({
            "type": "retry",
            "operation": operation,
            "attempt": attempt,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def log_interrupt(
        self,
        event: str,
        artifact_path: str = "",
    ) -> None:
        """
        Emit a structured log entry for an interrupt event.

        Args:
            event: One of "raised", "approved", "rejected", "timeout".
            artifact_path: Path of the artifact involved in the interrupt.
        """
        self.log({
            "type": "interrupt",
            "event": event,
            "artifact_path": artifact_path,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
