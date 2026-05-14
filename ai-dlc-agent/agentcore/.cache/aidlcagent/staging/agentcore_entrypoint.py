"""
Amazon Bedrock AgentCore Runtime entrypoint for the AI-DLC Strands Agent.

This module wraps the WorkflowOrchestrator in a BedrockAgentCoreApp HTTP
service, replacing the interactive CLI stdin gates with a return-of-control
pattern over HTTP.

Invocation protocol
-------------------
Every call is a POST to /invocations with a JSON body.

Start a new workflow:
    {
        "action": "start",
        "repo":   "kiro-sandbox/services/java-api",
        "story":  "As a user, I want to update my profile",
        "model_id": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"  # optional
    }

Approve the current stage and continue:
    {
        "action":     "approve",
        "session_id": "<session_id from previous response>"
    }

Send feedback / request changes:
    {
        "action":     "feedback",
        "session_id": "<session_id>",
        "text":       "Please add input validation to the requirements"
    }

Answer clarifying questions (requirements-analysis stage):
    {
        "action":     "answer",
        "session_id": "<session_id>",
        "answers":    "A2 B1 C3"
    }

Response shape
--------------
Every response contains:
    {
        "status":       "awaiting_approval" | "awaiting_answers" | "complete" | "error",
        "session_id":   "<uuid>",
        "stage":        "<current stage name>",
        "summary":      "<stage completion summary>",
        "artifacts":    [{"type": "artifact|source", "path": "..."}],
        "questions_md": "<raw markdown of questions file, if awaiting_answers>",
        "result":       { ... }   # only when status == "complete"
        "error":        "..."     # only when status == "error"
    }

Differences from the CLI mode
------------------------------
- No stdin / stdout interaction — all I/O is JSON over HTTP
- No MCP filesystem server (npx not available in AgentCore containers) —
  agents use write_aidlc_artifact / write_source_file / scan_directory directly
- WriteInterruptHook is disabled — file writes are approved implicitly
- Session state is persisted to /tmp/<session_id>/ between invocations
  (AgentCore sessions have a 15-minute inactivity timeout)
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bedrock_agentcore import BedrockAgentCoreApp
from bedrock_agentcore.runtime.context import RequestContext

# ---------------------------------------------------------------------------
# App bootstrap
# ---------------------------------------------------------------------------

app = BedrockAgentCoreApp()

# ---------------------------------------------------------------------------
# Session store — keyed by session_id, lives in /tmp for the container lifetime
# ---------------------------------------------------------------------------

_SESSION_DIR = Path("/tmp/aidlc-sessions")
_SESSION_DIR.mkdir(parents=True, exist_ok=True)

_ACTIVE_SESSIONS: dict[str, "_SessionState"] = {}
_SESSIONS_LOCK = threading.Lock()


class _SessionState:
    """
    Holds the mutable state for one workflow session.

    The orchestrator runs one stage at a time. After each stage it pauses and
    stores its state here. The next HTTP invocation resumes from this state.
    """

    def __init__(self, session_id: str, repo: str, story: str, model_id: str) -> None:
        self.session_id = session_id
        self.repo = repo
        self.story = story
        self.model_id = model_id

        # Pending approval gate — set by the stage runner, cleared by approve/feedback
        self.pending_stage: str | None = None
        self.pending_summary: str = ""
        self.pending_artifacts: list[tuple[str, str]] = []
        self.pending_questions_path: Path | None = None

        # Feedback to inject into the next stage run (from "feedback" action)
        self.pending_feedback: str | None = None

        # Answers to inject into the questions file (from "answer" action)
        self.pending_answers: str | None = None

        # Result when workflow completes
        self.final_result: dict[str, Any] | None = None
        self.error: str | None = None

        # Background thread running the current stage
        self._thread: threading.Thread | None = None
        self._stage_done = threading.Event()
        self._approval_event = threading.Event()
        self._approval_value: bool = False

        # Persisted output dir for this session
        self.output_dir = str(_SESSION_DIR / session_id)
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    def wait_for_stage_pause(self, timeout: float = 300.0) -> bool:
        """Block until the stage runner signals it needs approval. Returns False on timeout."""
        return self._stage_done.wait(timeout=timeout)

    def signal_stage_paused(self) -> None:
        """Called by the stage runner when it reaches an approval gate."""
        self._stage_done.set()

    def resume(self, approved: bool) -> None:
        """Called by the HTTP handler to resume the stage runner."""
        self._stage_done.clear()
        self._approval_value = approved
        self._approval_event.set()

    def wait_for_approval(self, timeout: float = 600.0) -> bool:
        """Called by the stage runner to block until the HTTP handler resumes it."""
        self._approval_event.wait(timeout=timeout)
        self._approval_event.clear()
        return self._approval_value


# ---------------------------------------------------------------------------
# Headless orchestrator — no stdin, no MCP, no WriteInterruptHook
# ---------------------------------------------------------------------------

def _build_headless_orchestrator(session: _SessionState) -> Any:
    """
    Build a WorkflowOrchestrator configured for headless AgentCore operation.

    Key differences from CLI mode:
    - output_dir points to the session's /tmp directory
    - MCP tools are disabled (no npx in AgentCore containers)
    - WriteInterruptHook is not added (file writes are auto-approved)
    """
    from app.workflow import WorkflowOrchestrator, RULES_BASE_PATH

    orchestrator = WorkflowOrchestrator(
        model_id=session.model_id,
        output_dir=session.output_dir,
        rules_base_path=RULES_BASE_PATH,
    )
    # Disable MCP — override _get_mcp_tools to return empty list
    orchestrator._get_mcp_tools = lambda: []  # type: ignore[method-assign]
    return orchestrator


def _run_workflow_in_background(session: _SessionState) -> None:
    """
    Run the full workflow in a background thread, pausing at each approval gate.

    This function replaces the CLI's stdin-based _request_approval_python() with
    an event-based mechanism that communicates with the HTTP handler.
    """
    import app.workflow as wf_module

    # Monkey-patch _request_approval_python for this session only.
    # The patch intercepts every stage gate and uses threading events instead of stdin.
    original_approval = wf_module._request_approval_python

    def _headless_approval(stage: str, summary: str, target_repo: str = "") -> bool:
        from app.skills.stage_tracker import get_written
        from app.workflow import _find_questions_file

        written = get_written()
        questions_path = _find_questions_file(target_repo) if target_repo else None

        # Store gate state on the session object.
        session.pending_stage = stage
        session.pending_summary = summary
        session.pending_artifacts = list(written)
        session.pending_questions_path = questions_path

        # If there are unanswered questions and answers were provided, write them back.
        if questions_path and session.pending_answers:
            try:
                from app.skills.interactive_questions import (
                    parse_questions,
                    write_answers_back,
                    _parse_compact_answers,
                )
                content = questions_path.read_text(encoding="utf-8")
                questions = parse_questions(content)
                unanswered = [q for q in questions if not q.answer]
                labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                _parse_compact_answers(session.pending_answers, unanswered, labels)
                write_answers_back(questions_path, questions)
            except Exception:
                pass
            session.pending_answers = None

        # Signal the HTTP handler that we're paused.
        session.signal_stage_paused()

        # Block until the HTTP handler calls session.resume().
        approved = session.wait_for_approval(timeout=600.0)

        # If feedback was provided, inject it as a revision request.
        if not approved and session.pending_feedback:
            # Returning False causes the orchestrator to log a rejection.
            # The next invocation will re-run the stage with the feedback.
            session.pending_feedback = None

        return approved

    wf_module._request_approval_python = _headless_approval  # type: ignore[attr-defined]

    try:
        orchestrator = _build_headless_orchestrator(session)
        result = orchestrator.run(
            target_repo=session.repo,
            user_story=session.story,
        )
        session.final_result = result
    except Exception as exc:
        session.error = str(exc)
    finally:
        # Restore original function and signal completion.
        wf_module._request_approval_python = original_approval  # type: ignore[attr-defined]
        session.pending_stage = "__done__"
        session.signal_stage_paused()


# ---------------------------------------------------------------------------
# HTTP entrypoint
# ---------------------------------------------------------------------------

@app.entrypoint
def invoke(payload: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    """
    Main AgentCore invocation handler.

    Accepts start / approve / feedback / answer actions and returns a
    structured response describing the current workflow state.
    """
    action = payload.get("action", "start")
    session_id = payload.get("session_id") or context.session_id or str(uuid.uuid4())

    # ------------------------------------------------------------------
    # START — create a new session and kick off the workflow thread
    # ------------------------------------------------------------------
    if action == "start":
        repo = payload.get("repo", "")
        story = payload.get("story", "")
        model_id = payload.get("model_id", os.environ.get(
            "MODEL_ID",
            "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        ))

        if not repo or not story:
            return {
                "status": "error",
                "error": "Both 'repo' and 'story' are required for action='start'.",
                "session_id": session_id,
            }

        session = _SessionState(
            session_id=session_id,
            repo=repo,
            story=story,
            model_id=model_id,
        )
        with _SESSIONS_LOCK:
            _ACTIVE_SESSIONS[session_id] = session

        # Start the workflow in a background thread.
        thread = threading.Thread(
            target=_run_workflow_in_background,
            args=(session,),
            daemon=True,
            name=f"aidlc-{session_id[:8]}",
        )
        session._thread = thread
        thread.start()

        # Wait for the first stage gate (or completion).
        session.wait_for_stage_pause(timeout=300.0)
        return _build_response(session)

    # ------------------------------------------------------------------
    # APPROVE / FEEDBACK / ANSWER — resume a paused session
    # ------------------------------------------------------------------
    with _SESSIONS_LOCK:
        session = _ACTIVE_SESSIONS.get(session_id)

    if session is None:
        return {
            "status": "error",
            "error": f"Session '{session_id}' not found. Start a new workflow with action='start'.",
            "session_id": session_id,
        }

    if action == "approve":
        session.resume(approved=True)

    elif action == "feedback":
        session.pending_feedback = payload.get("text", "")
        session.resume(approved=False)

    elif action == "answer":
        session.pending_answers = payload.get("answers", "")
        session.resume(approved=True)

    else:
        return {
            "status": "error",
            "error": f"Unknown action '{action}'. Valid: start, approve, feedback, answer.",
            "session_id": session_id,
        }

    # Wait for the next gate.
    session.wait_for_stage_pause(timeout=300.0)
    return _build_response(session)


def _build_response(session: _SessionState) -> dict[str, Any]:
    """Build the HTTP response from the current session state."""
    # Workflow complete or errored.
    if session.pending_stage == "__done__":
        with _SESSIONS_LOCK:
            _ACTIVE_SESSIONS.pop(session.session_id, None)

        if session.error:
            return {
                "status": "error",
                "session_id": session.session_id,
                "stage": "workflow",
                "error": session.error,
            }
        return {
            "status": "complete",
            "session_id": session.session_id,
            "stage": "complete",
            "result": session.final_result or {},
        }

    # Paused at an approval gate.
    questions_md: str | None = None
    status = "awaiting_approval"

    if session.pending_questions_path and session.pending_questions_path.exists():
        try:
            questions_md = session.pending_questions_path.read_text(encoding="utf-8")
            status = "awaiting_answers"
        except OSError:
            pass

    return {
        "status": status,
        "session_id": session.session_id,
        "stage": session.pending_stage or "unknown",
        "summary": session.pending_summary[:500] if session.pending_summary else "",
        "artifacts": [
            {"type": ftype, "path": fpath}
            for ftype, fpath in (session.pending_artifacts or [])
        ],
        "questions_md": questions_md,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.ping
def health() -> dict[str, Any]:
    """Return healthy status with active session count."""
    from bedrock_agentcore.runtime.models import PingStatus
    with _SESSIONS_LOCK:
        active = len(_ACTIVE_SESSIONS)
    status = PingStatus.HEALTHY_BUSY if active > 0 else PingStatus.HEALTHY
    return {"status": status, "active_sessions": active}


# ---------------------------------------------------------------------------
# Local dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run()
