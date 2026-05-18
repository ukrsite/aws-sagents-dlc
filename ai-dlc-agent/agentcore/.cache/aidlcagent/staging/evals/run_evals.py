"""Evaluation suite for the AI-DLC Strands Agent.

Uses the ``strands-agents-evals`` SDK (imported as ``strands_evals``) to run
five test cases against the WorkflowOrchestrator and evaluate agent output
using four evaluators:

- StateFileEvaluator        — aidlc-state.md created with expected stage entries
- AuditLogEvaluator         — audit.md contains timestamped entries
- ClarificationEvaluator    — agent requests clarification for ambiguous input
- SteeringViolationEvaluator — agent refuses off-topic requests

Usage:
    python evals/run_evals.py

Exit codes:
    0 — all cases passed
    1 — one or more cases failed
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

# Ensure the ai-dlc-agent package is importable when run from the evals/ directory.
sys.path.insert(0, str(Path(__file__).parent.parent))

from strands_evals import Case, Experiment
from strands_evals.evaluators import Evaluator
from strands_evals.types import EvaluationData, EvaluationOutput

from app.workflow import WorkflowOrchestrator

# ---------------------------------------------------------------------------
# Workspace root (two levels above ai-dlc-agent/)
# ---------------------------------------------------------------------------
_WORKSPACE_ROOT = Path(__file__).parent.parent.parent.resolve()
_EVAL_WORKSPACES = Path(__file__).parent / ".workspaces"
_DEFAULT_MODEL_ID = os.environ.get(
    "MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
)


# ---------------------------------------------------------------------------
# Task helpers — strands_evals 0.2+ expects {"output": ...} when returning dicts
# ---------------------------------------------------------------------------

def _wrap_output(payload: Any) -> dict[str, Any]:
    """Wrap task result for Experiment (dict returns must use an ``output`` key)."""
    return {"output": payload}


def _extract_response_text(actual_output: Any) -> str:
    """Normalize agent/task output to searchable text for evaluators."""
    if actual_output is None:
        return ""
    if isinstance(actual_output, str):
        return actual_output
    if isinstance(actual_output, dict):
        for key in ("response", "message", "text", "error"):
            value = actual_output.get(key)
            if value:
                return str(value)
        return json.dumps(actual_output, ensure_ascii=False)
    return str(actual_output)


def _prepare_target_repo(case: Case) -> tuple[str, str]:
    """
    Resolve the target repo for a case.

    Returns:
        ``(raw_repo, absolute_path)`` where *raw_repo* is passed to the orchestrator.
    """
    meta = case.metadata or {}
    base = meta.get("target_repo", "kiro-sandbox/services/java-api")
    source = _WORKSPACE_ROOT / base

    if not meta.get("isolate_workspace"):
        abs_path = str(source.resolve())
        return base, abs_path

    workspace = _EVAL_WORKSPACES / (case.name or "case")
    if workspace.exists():
        shutil.rmtree(workspace)

    if source.is_dir():
        def _ignore(directory: str, names: list[str]) -> list[str]:
            ignored: list[str] = []
            if "aidlc-docs" in names:
                ignored.append("aidlc-docs")
            for name in names:
                if name in (".git", "__pycache__", ".venv", "node_modules"):
                    ignored.append(name)
            return ignored

        shutil.copytree(source, workspace, ignore=_ignore)
    else:
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "README.md").write_text(
            "# Eval workspace\n\nMinimal repo stub for isolated evaluation runs.\n",
            encoding="utf-8",
        )

    rel = str(workspace.relative_to(_WORKSPACE_ROOT))
    return rel, str(workspace.resolve())


def _run_story_intake(user_story: str, model_id: str) -> str:
    """
    Single-turn intake gate: refuse off-topic input or ask for clarification.

    Uses a lightweight Strands agent (no tools) so steering/clarification cases
    exercise real model output without running the full workflow.
    """
    from strands import Agent
    from strands.models import BedrockModel

    system_prompt = """You are the intake gate for an AI-DLC software development lifecycle agent.

Rules:
- Only accept requests related to software development (user stories, features, bugs, refactors, SDLC work).
- If the request is off-topic (poems, jokes, general chat, unrelated tasks), refuse politely. State that you can only assist with software development lifecycle activities.
- If the user story is too vague or ambiguous (e.g. "improve my app" with no specifics), ask clarifying questions. Use lines ending with `[Answer]:` for each question.
- If the input is a clear, valid software user story, reply with exactly: ACCEPTED

Keep responses concise."""

    agent = Agent(
        name="eval_intake_agent",
        model=BedrockModel(
            model_id=model_id,
            max_tokens=1024,
            boto_client_config=__import__("botocore.config", fromlist=["Config"]).Config(
                read_timeout=120,
                connect_timeout=30,
                retries={"max_attempts": 2, "mode": "adaptive"},
            ),
        ),
        system_prompt=system_prompt,
        tools=[],
        callback_handler=None,
    )
    return str(agent(user_story))


# ---------------------------------------------------------------------------
# Task function — invoked by Experiment.run_evaluations() for each Case
# ---------------------------------------------------------------------------

def run_agent(case: Case) -> dict[str, Any]:
    """
    Invoke the agent for the given evaluation case.

    Steering and clarification cases call a real intake agent on an isolated
    workspace. Workflow cases invoke WorkflowOrchestrator (session resumption
    skips already-completed stages for faster runs).
    """
    meta = case.metadata or {}
    user_story: str = case.input
    raw_repo, target_repo = _prepare_target_repo(case)
    model_id = meta.get("model_id", _DEFAULT_MODEL_ID)

    if meta.get("violates_steering") or meta.get("requires_clarification"):
        try:
            response = _run_story_intake(user_story, model_id)
        except Exception as exc:
            return _wrap_output({
                "target_repo": target_repo,
                "user_story": user_story,
                "mode": "intake",
                "error": str(exc),
            })
        return _wrap_output({
            "target_repo": target_repo,
            "user_story": user_story,
            "mode": "intake",
            "response": response,
        })

    try:
        orchestrator = WorkflowOrchestrator(model_id=model_id)
        result = orchestrator.run(target_repo=raw_repo, user_story=user_story)
        result["target_repo"] = target_repo
        return _wrap_output(result)
    except Exception as exc:
        return _wrap_output({
            "target_repo": target_repo,
            "user_story": user_story,
            "error": str(exc),
        })


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _resolve_target_repo(evaluation_case: EvaluationData) -> str:
    """Get the absolute target_repo path from output or metadata."""
    output = evaluation_case.actual_output or {}
    if isinstance(output, dict) and output.get("target_repo"):
        return str(output["target_repo"])
    meta = evaluation_case.metadata or {}
    raw = meta.get("target_repo", "kiro-sandbox/services/java-api")
    if meta.get("isolate_workspace") and evaluation_case.name:
        isolated = _EVAL_WORKSPACES / evaluation_case.name
        if isolated.exists():
            return str(isolated.resolve())
    return str((_WORKSPACE_ROOT / raw).resolve())


def _aggregate_case_passes(reports: list, num_cases: int) -> list[bool]:
    """True when every evaluator passed for that case index."""
    passes = [True] * num_cases
    for report in reports:
        for i, ok in enumerate(report.test_passes):
            if i < num_cases and not ok:
                passes[i] = False
    return passes


# ---------------------------------------------------------------------------
# Evaluators
# ---------------------------------------------------------------------------

class StateFileEvaluator(Evaluator):
    """
    Verifies that ``{target_repo}/aidlc-docs/aidlc-state.md`` is created and
    contains the expected stage completion entries.
    """

    def evaluate(self, evaluation_case: EvaluationData) -> list[EvaluationOutput]:
        meta = evaluation_case.metadata or {}
        target_repo = _resolve_target_repo(evaluation_case)
        state_path = Path(target_repo) / "aidlc-docs" / "aidlc-state.md"

        if not meta.get("state_file_created", False):
            if state_path.exists():
                return [EvaluationOutput(
                    score=0.0,
                    test_pass=False,
                    reason="aidlc-state.md exists but should not for this case",
                    label="StateFileEvaluator",
                )]
            return [EvaluationOutput(
                score=1.0, test_pass=True, reason="Passed", label="StateFileEvaluator",
            )]

        if not state_path.exists():
            return [EvaluationOutput(
                score=0.0,
                test_pass=False,
                reason=f"aidlc-state.md not found at {state_path}",
                label="StateFileEvaluator",
            )]

        text = state_path.read_text(encoding="utf-8")
        match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if not match:
            return [EvaluationOutput(
                score=0.0,
                test_pass=False,
                reason="aidlc-state.md does not contain a valid JSON block",
                label="StateFileEvaluator",
            )]

        try:
            state = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            return [EvaluationOutput(
                score=0.0,
                test_pass=False,
                reason=f"aidlc-state.md JSON block is not parseable: {exc}",
                label="StateFileEvaluator",
            )]

        for field in ("last_completed_stage", "completed_stages", "current_stage", "updated_at"):
            if field not in state:
                return [EvaluationOutput(
                    score=0.0,
                    test_pass=False,
                    reason=f"aidlc-state.md missing required field: {field}",
                    label="StateFileEvaluator",
                )]

        expected_project_type = meta.get("project_type")
        if expected_project_type:
            actual_type = str(state.get("project_type", "")).lower()
            if actual_type not in (expected_project_type.lower(), "unknown"):
                return [EvaluationOutput(
                    score=0.0,
                    test_pass=False,
                    reason=(
                        f"Expected project_type '{expected_project_type}', "
                        f"got '{state.get('project_type')}'"
                    ),
                    label="StateFileEvaluator",
                )]

        completed = state.get("completed_stages", [])
        min_stages = meta.get("completed_stages_min", 0)
        if len(completed) < min_stages:
            return [EvaluationOutput(
                score=0.0,
                test_pass=False,
                reason=f"Expected ≥{min_stages} completed stage(s), got {len(completed)}: {completed}",
                label="StateFileEvaluator",
            )]

        for stage in meta.get("expected_stages", []):
            if stage not in completed:
                return [EvaluationOutput(
                    score=0.0,
                    test_pass=False,
                    reason=f"Expected stage '{stage}' not in completed_stages: {completed}",
                    label="StateFileEvaluator",
                )]

        return [EvaluationOutput(
            score=1.0, test_pass=True, reason="Passed", label="StateFileEvaluator",
        )]


class AuditLogEvaluator(Evaluator):
    """
    Verifies that ``{target_repo}/aidlc-docs/audit.md`` contains timestamped
    entries for stage approval interactions.
    """

    def evaluate(self, evaluation_case: EvaluationData) -> list[EvaluationOutput]:
        meta = evaluation_case.metadata or {}
        target_repo = _resolve_target_repo(evaluation_case)
        min_entries = meta.get("audit_entries_min", 0)

        if min_entries == 0:
            return [EvaluationOutput(
                score=1.0,
                test_pass=True,
                reason="No audit entries required",
                label="AuditLogEvaluator",
            )]

        audit_path = Path(target_repo) / "aidlc-docs" / "audit.md"
        if not audit_path.exists():
            return [EvaluationOutput(
                score=0.0,
                test_pass=False,
                reason=f"audit.md not found at {audit_path}",
                label="AuditLogEvaluator",
            )]

        text = audit_path.read_text(encoding="utf-8")
        entries = re.findall(r"^## .+", text, re.MULTILINE)
        if len(entries) < min_entries:
            return [EvaluationOutput(
                score=0.0,
                test_pass=False,
                reason=f"Expected ≥{min_entries} audit entry/entries, found {len(entries)}",
                label="AuditLogEvaluator",
            )]

        timestamps = re.findall(r"\*\*Timestamp\*\*:", text)
        if len(timestamps) < min_entries:
            return [EvaluationOutput(
                score=0.0,
                test_pass=False,
                reason=f"Expected ≥{min_entries} timestamped entries, found {len(timestamps)}",
                label="AuditLogEvaluator",
            )]

        return [EvaluationOutput(
            score=1.0, test_pass=True, reason="Passed", label="AuditLogEvaluator",
        )]


class ClarificationEvaluator(Evaluator):
    """
    Verifies that the agent requests clarification (using ``[Answer]:`` tags or
    question marks) when the input description is ambiguous.
    """

    _PATTERNS = [
        r"\[Answer\]:", r"\?", r"clarif", r"could you please",
        r"can you provide", r"please specify",
    ]

    def evaluate(self, evaluation_case: EvaluationData) -> list[EvaluationOutput]:
        meta = evaluation_case.metadata or {}
        if not meta.get("requires_clarification", False):
            return [EvaluationOutput(
                score=1.0,
                test_pass=True,
                reason="Clarification not required",
                label="ClarificationEvaluator",
            )]

        output_text = _extract_response_text(evaluation_case.actual_output).lower()
        for pattern in self._PATTERNS:
            if re.search(pattern, output_text, re.IGNORECASE):
                return [EvaluationOutput(
                    score=1.0, test_pass=True, reason="Passed", label="ClarificationEvaluator",
                )]

        return [EvaluationOutput(
            score=0.0,
            test_pass=False,
            reason=f"Agent did not request clarification. output_text[:200]={output_text[:200]}",
            label="ClarificationEvaluator",
        )]


class SteeringViolationEvaluator(Evaluator):
    """
    Verifies that the agent refuses off-topic requests with a polite explanation.
    """

    _PATTERNS = [
        r"outside my scope", r"can only assist", r"not able to help",
        r"cannot help", r"off.?topic", r"software development",
        r"lifecycle activities", r"sorry", r"apologize",
    ]

    def evaluate(self, evaluation_case: EvaluationData) -> list[EvaluationOutput]:
        meta = evaluation_case.metadata or {}
        if not meta.get("violates_steering", False):
            return [EvaluationOutput(
                score=1.0,
                test_pass=True,
                reason="Steering violation not expected",
                label="SteeringViolationEvaluator",
            )]

        output_text = _extract_response_text(evaluation_case.actual_output).lower()
        for pattern in self._PATTERNS:
            if re.search(pattern, output_text, re.IGNORECASE):
                return [EvaluationOutput(
                    score=1.0, test_pass=True, reason="Passed", label="SteeringViolationEvaluator",
                )]

        return [EvaluationOutput(
            score=0.0,
            test_pass=False,
            reason="Agent did not refuse the off-topic request.",
            label="SteeringViolationEvaluator",
        )]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Run all evaluation cases and print a summary report."""
    cases_path = Path(__file__).parent / "cases.json"
    with open(cases_path, encoding="utf-8") as fh:
        raw_cases = json.load(fh)

    cases = [
        Case(
            name=c["name"],
            input=c["user_story"],
            metadata={
                "target_repo": c.get("target_repo", "kiro-sandbox/services/java-api"),
                "isolate_workspace": c.get("isolate_workspace", False),
                **c["expected"],
            },
        )
        for c in raw_cases
    ]

    experiment = Experiment(
        cases=cases,
        evaluators=[
            StateFileEvaluator(),
            AuditLogEvaluator(),
            ClarificationEvaluator(),
            SteeringViolationEvaluator(),
        ],
    )

    print("\n" + "=" * 70)
    print("AI-DLC Strands Agent — Evaluation Suite")
    print("=" * 70)

    reports = experiment.run_evaluations(run_agent)

    case_passes = _aggregate_case_passes(reports, len(cases))
    all_passed = all(case_passes)

    for report in reports:
        report.display()

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    passed_count = sum(case_passes)
    print(f"Passed: {passed_count}/{len(cases)} cases")
    for case, ok in zip(cases, case_passes):
        if ok:
            continue
        print(f"\n  FAILED: {case.name}")
        for report in reports:
            idx = cases.index(case)
            if idx < len(report.test_passes) and not report.test_passes[idx]:
                evaluator = report.evaluator_name or "evaluator"
                reason = report.reasons[idx] if idx < len(report.reasons) else ""
                print(f"    - {evaluator}: {reason}")
    print()

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
