"""
Amazon Bedrock AgentCore Runtime entrypoint for the AI-DLC Strands Agent.

This module wraps the WorkflowOrchestrator in a BedrockAgentCoreApp HTTP
service, replacing the interactive CLI stdin gates with a return-of-control
pattern over HTTP.

Invocation protocol
-------------------
Every call is a POST to /invocations with a JSON body.

Start a new workflow (auto-approve mode — runs end-to-end, pauses only for questions):
    {
        "action":       "start",
        "repo":         "kiro-sandbox/services/java-api",
        "story":        "As a user, I want to update my profile",
        "model_id":     "us.anthropic.claude-sonnet-4-5-20250929-v1:0",  # optional
        "auto_approve": true   # default: true — skip per-stage approval gates
    }

Answer clarifying questions (only needed when status == "awaiting_answers"):
    {
        "action":     "answer",
        "session_id": "<session_id from previous response>",
        "answers":    "A2 B1 C3"
    }

Manual approve (only needed when auto_approve=false):
    {
        "action":     "approve",
        "session_id": "<session_id>"
    }

Send feedback / request changes (only needed when auto_approve=false):
    {
        "action":     "feedback",
        "session_id": "<session_id>",
        "text":       "Please add input validation to the requirements"
    }

Response shape
--------------
Every response contains:
    {
        "status":       "running" | "awaiting_answers" | "complete" | "error",
        "session_id":   "<uuid>",
        "stage":        "<last completed stage name>",
        "completed_stages": ["workspace-detection", ...],
        "artifacts":    [{"type": "artifact|source", "path": "..."}],
        "questions_md": "<raw markdown — only when status=awaiting_answers>",
        "result":       { ... }   # only when status == "complete"
        "error":        "..."     # only when status == "error"
    }

Differences from the CLI mode
------------------------------
- No stdin / stdout interaction — all I/O is JSON over HTTP
- auto_approve=true (default): all stage gates are skipped automatically;
  the workflow only pauses when clarifying questions need answers
- No MCP filesystem server (npx not available in AgentCore containers) —
  agents use write_aidlc_artifact / write_source_file / scan_directory directly
- WriteInterruptHook is disabled — file writes are auto-approved
- Session state is persisted to /tmp/<session_id>/ between invocations
  (AgentCore sessions have a 15-minute inactivity timeout)
"""

from __future__ import annotations

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
    """Holds the mutable state for one workflow session."""

    def __init__(
        self,
        session_id: str,
        repo: str,
        story: str,
        model_id: str,
        auto_approve: bool = True,
    ) -> None:
        self.session_id = session_id
        self.repo = repo
        self.story = story
        self.model_id = model_id
        self.auto_approve = auto_approve

        # Gate state — populated when the workflow pauses
        self.pending_stage: str | None = None
        self.pending_artifacts: list[tuple[str, str]] = []
        self.pending_questions_path: Path | None = None
        self.completed_stages: list[str] = []

        # Answers to inject into the questions file (from "answer" action)
        self.pending_answers: str | None = None

        # Feedback for manual mode (from "feedback" action)
        self.pending_feedback: str | None = None

        # Final result / error
        self.final_result: dict[str, Any] | None = None
        self.error: str | None = None

        # Threading primitives
        self._thread: threading.Thread | None = None
        self._stage_done = threading.Event()
        self._approval_event = threading.Event()
        self._approval_value: bool = False

        # Per-session output dir
        self.output_dir = str(_SESSION_DIR / session_id)
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    # -- called by the HTTP handler to wait for the workflow to pause --

    def wait_for_pause(self, timeout: float = 600.0) -> bool:
        """Block until the workflow thread signals a pause. Returns False on timeout."""
        return self._stage_done.wait(timeout=timeout)

    # -- called by the workflow thread --

    def signal_paused(self) -> None:
        self._stage_done.set()

    def wait_for_resume(self, timeout: float = 600.0) -> bool:
        """Block the workflow thread until the HTTP handler resumes it."""
        self._approval_event.wait(timeout=timeout)
        self._approval_event.clear()
        return self._approval_value

    # -- called by the HTTP handler to resume the workflow thread --

    def resume(self, approved: bool) -> None:
        self._stage_done.clear()
        self._approval_value = approved
        self._approval_event.set()


# ---------------------------------------------------------------------------
# Headless orchestrator
# ---------------------------------------------------------------------------

def _build_headless_orchestrator(session: _SessionState) -> Any:
    """Build a WorkflowOrchestrator with MCP and WriteInterruptHook disabled."""
    from app.workflow import WorkflowOrchestrator, RULES_BASE_PATH

    orchestrator = WorkflowOrchestrator(
        model_id=session.model_id,
        output_dir=session.output_dir,
        rules_base_path=RULES_BASE_PATH,
    )
    orchestrator._get_mcp_tools = lambda: []  # type: ignore[method-assign]
    return orchestrator


def _run_workflow_in_background(session: _SessionState) -> None:
    """
    Run the full workflow in a background thread.

    Replaces _request_approval_python with a headless version that:
    - auto-approves all stage gates when session.auto_approve is True
    - pauses only when clarifying questions need answers (any mode)
    - pauses at every gate when auto_approve is False (manual mode)
    """
    import app.workflow as wf_module

    original_approval = wf_module._request_approval_python

    def _headless_approval(stage: str, summary: str, target_repo: str = "") -> bool:
        from app.skills.stage_tracker import get_written
        from app.workflow import _find_questions_file

        written = get_written()
        questions_path = _find_questions_file(target_repo) if target_repo else None

        # Track completed stages for the response.
        if stage not in session.completed_stages:
            session.completed_stages.append(stage)

        session.pending_stage = stage
        session.pending_artifacts = list(written)
        session.pending_questions_path = questions_path

        # Write answers back into the questions file if provided.
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
                _parse_compact_answers(session.pending_answers, unanswered, questions)
                write_answers_back(questions_path, questions)
            except Exception:
                pass
            session.pending_answers = None

        # Determine whether to pause or auto-continue.
        has_unanswered_questions = False
        if questions_path and questions_path.exists() and stage == "requirements-analysis":
            try:
                from app.skills.interactive_questions import parse_questions
                qs = parse_questions(questions_path.read_text(encoding="utf-8"))
                has_unanswered_questions = any(not q.answer for q in qs)
            except Exception:
                pass

        # Always pause when there are unanswered questions — regardless of auto_approve.
        if has_unanswered_questions:
            session.signal_paused()
            return session.wait_for_resume(timeout=600.0)

        # In auto_approve mode, skip the gate and continue immediately.
        if session.auto_approve:
            return True

        # Manual mode — pause and wait for HTTP approval.
        session.signal_paused()
        approved = session.wait_for_resume(timeout=600.0)
        if not approved and session.pending_feedback:
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
        wf_module._request_approval_python = original_approval  # type: ignore[attr-defined]
        session.pending_stage = "__done__"
        session.signal_paused()


# ---------------------------------------------------------------------------
# HTTP entrypoint
# ---------------------------------------------------------------------------

@app.entrypoint
def invoke(payload: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    """
    Main AgentCore invocation handler.

    Actions: start | answer | approve | feedback
    """
    action = payload.get("action", "start")
    session_id = payload.get("session_id") or context.session_id or str(uuid.uuid4())

    # ------------------------------------------------------------------
    # START
    # ------------------------------------------------------------------
    if action == "start":
        repo = payload.get("repo", "")
        story = payload.get("story", "")
        if not repo or not story:
            return {
                "status": "error",
                "error": "'repo' and 'story' are required for action='start'.",
                "session_id": session_id,
            }

        model_id = payload.get("model_id", os.environ.get(
            "MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        ))
        auto_approve = payload.get("auto_approve", True)

        session = _SessionState(
            session_id=session_id,
            repo=repo,
            story=story,
            model_id=model_id,
            auto_approve=auto_approve,
        )
        with _SESSIONS_LOCK:
            _ACTIVE_SESSIONS[session_id] = session

        thread = threading.Thread(
            target=_run_workflow_in_background,
            args=(session,),
            daemon=True,
            name=f"aidlc-{session_id[:8]}",
        )
        session._thread = thread
        thread.start()

        # In auto_approve mode the workflow runs until it hits questions or finishes.
        # Wait up to 10 minutes for the first pause point.
        session.wait_for_pause(timeout=600.0)
        return _build_response(session)

    # ------------------------------------------------------------------
    # ANSWER / APPROVE / FEEDBACK — resume a paused session
    # ------------------------------------------------------------------
    with _SESSIONS_LOCK:
        session = _ACTIVE_SESSIONS.get(session_id)

    if session is None:
        return {
            "status": "error",
            "error": f"Session '{session_id}' not found. Use action='start' to begin.",
            "session_id": session_id,
        }

    if action == "answer":
        session.pending_answers = payload.get("answers", "")
        session.resume(approved=True)

    elif action == "approve":
        session.resume(approved=True)

    elif action == "feedback":
        session.pending_feedback = payload.get("text", "")
        session.resume(approved=False)

    else:
        return {
            "status": "error",
            "error": f"Unknown action '{action}'. Valid: start, answer, approve, feedback.",
            "session_id": session_id,
        }

    session.wait_for_pause(timeout=600.0)
    return _build_response(session)


def _build_response(session: _SessionState) -> dict[str, Any]:
    """Build the HTTP response from the current session state."""
    if session.pending_stage == "__done__":
        with _SESSIONS_LOCK:
            _ACTIVE_SESSIONS.pop(session.session_id, None)

        if session.error:
            return {
                "status": "error",
                "session_id": session.session_id,
                "completed_stages": session.completed_stages,
                "error": session.error,
            }
        return {
            "status": "complete",
            "session_id": session.session_id,
            "completed_stages": session.completed_stages,
            "result": session.final_result or {},
        }

    # Paused — check if it's for questions or manual approval.
    questions_md: str | None = None
    status = "running" if session.auto_approve else "awaiting_approval"

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
        "completed_stages": session.completed_stages,
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
    """Return healthy/busy status based on active session count."""
    from bedrock_agentcore.runtime.models import PingStatus
    with _SESSIONS_LOCK:
        active = len(_ACTIVE_SESSIONS)
    return {
        "status": PingStatus.HEALTHY_BUSY if active > 0 else PingStatus.HEALTHY,
        "active_sessions": active,
    }


# ---------------------------------------------------------------------------
# Local dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run()
