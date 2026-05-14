"""Skill: update aidlc-state.md and append to audit.md in the target repo."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from strands import tool

from app.skills.load_rule_file import KNOWN_STAGES

# Ordered list of all AI-DLC stages for determining "next stage".
STAGE_ORDER: list[str] = KNOWN_STAGES


def _get_next_stage(current_stage: str) -> str:
    """Return the stage that follows current_stage, or 'complete' if last."""
    try:
        idx = STAGE_ORDER.index(current_stage)
        if idx + 1 < len(STAGE_ORDER):
            return STAGE_ORDER[idx + 1]
    except ValueError:
        pass
    return "complete"


def _read_state(state_path: Path) -> dict:
    """Parse the JSON block from aidlc-state.md, or return a fresh state dict."""
    if not state_path.exists():
        return {
            "project_type": "unknown",
            "workspace_root": str(state_path.parent.parent.resolve()),
            "last_completed_stage": "",
            "completed_stages": [],
            "current_stage": STAGE_ORDER[0],
            "updated_at": "",
        }

    text = state_path.read_text(encoding="utf-8")
    # Extract the first ```json ... ``` block.
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Fallback: return a fresh state if the file exists but has no valid JSON block.
    return {
        "project_type": "unknown",
        "workspace_root": str(state_path.parent.parent.resolve()),
        "last_completed_stage": "",
        "completed_stages": [],
        "current_stage": STAGE_ORDER[0],
        "updated_at": "",
    }


def _write_state(state_path: Path, state: dict) -> None:
    """Write the state dict as a Markdown file with an embedded JSON block."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    json_block = json.dumps(state, indent=2, ensure_ascii=False)
    content = f"""# AI-DLC State Tracking

This file tracks the progress of the AI-DLC workflow for this repository.
It is managed automatically by the AI-DLC Strands Agent — do not edit manually.

## Stage Progress

```json
{json_block}
```
"""
    state_path.write_text(content, encoding="utf-8")


def _append_audit(audit_path: Path, stage_name: str, status: str) -> None:
    """Append a timestamped entry to audit.md."""
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()

    entry = f"\n## {stage_name} — {status}\n**Timestamp**: {timestamp}\n\n---\n"

    if not audit_path.exists():
        header = "# AI-DLC Audit Log\n\nAll agent interactions are recorded here.\n"
        audit_path.write_text(header + entry, encoding="utf-8")
    else:
        with open(audit_path, "a", encoding="utf-8") as fh:
            fh.write(entry)


@tool
def update_workflow_state(target_repo: str, stage_name: str, status: str) -> str:
    """
    Update the AI-DLC workflow state after completing a stage.

    Updates ``{target_repo}/aidlc-docs/aidlc-state.md`` with the stage
    completion entry and appends a timestamped entry to
    ``{target_repo}/aidlc-docs/audit.md``.

    Args:
        target_repo: Path to the target repository (e.g.,
            ``kiro-sandbox/services/java-api``).
        stage_name: The AI-DLC stage that was just completed (e.g.,
            ``requirements-analysis``).
        status: Completion status string (e.g., ``"complete"``, ``"skipped"``,
            ``"failed"``).

    Returns:
        The updated state as a JSON string containing ``last_completed_stage``,
        ``completed_stages``, ``current_stage``, and ``updated_at`` fields.
    """
    abs_repo = Path(target_repo).resolve()
    aidlc_docs = abs_repo / "aidlc-docs"
    state_path = aidlc_docs / "aidlc-state.md"
    audit_path = aidlc_docs / "audit.md"

    # Read existing state (or create fresh).
    state = _read_state(state_path)

    # Update state fields.
    now = datetime.now(timezone.utc).isoformat()
    if stage_name not in state.get("completed_stages", []):
        state.setdefault("completed_stages", []).append(stage_name)
    state["last_completed_stage"] = stage_name
    state["current_stage"] = _get_next_stage(stage_name)
    state["updated_at"] = now

    # Persist state and audit entry.
    _write_state(state_path, state)
    _append_audit(audit_path, stage_name, status)

    # Print stage progress indicator.
    icon = "✅" if status in ("complete", "completed") else "⏭️" if status == "skipped" else "❌"
    try:
        from rich.console import Console
        Console().print(f"\n[bold]{icon}  Stage:[/bold] [yellow]{stage_name}[/yellow] → [dim]{status}[/dim]")
    except ImportError:
        print(f"\n{icon}  Stage: {stage_name} → {status}", flush=True)

    # Return the four required fields as a JSON string.
    result = {
        "last_completed_stage": state["last_completed_stage"],
        "completed_stages": state["completed_stages"],
        "current_stage": state["current_stage"],
        "updated_at": state["updated_at"],
    }
    return json.dumps(result, ensure_ascii=False)
