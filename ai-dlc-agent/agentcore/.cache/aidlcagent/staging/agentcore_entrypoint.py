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
        "model_id":     "us.anthropic.claude-haiku-4-5-20251001-v1:0",  # optional
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

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from dotenv import load_dotenv

from bedrock_agentcore import BedrockAgentCoreApp
from bedrock_agentcore.runtime.context import RequestContext

# ---------------------------------------------------------------------------
# App bootstrap
# ---------------------------------------------------------------------------

# Load .env file for local development (agentcore dev)
# Use explicit path to ensure it's loaded regardless of cwd
_env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=_env_path)

app = BedrockAgentCoreApp()

# ---------------------------------------------------------------------------
# Session store — persisted to S3 for cross-container persistence
# ---------------------------------------------------------------------------

_SESSION_DIR = Path("/tmp/aidlc-sessions")
_SESSION_DIR.mkdir(parents=True, exist_ok=True)

# S3 bucket for persistent session storage (set via environment variable)
_SESSION_BUCKET = os.environ.get("SESSION_BUCKET", "aidlc-agentcore-sessions")

# For local development, disable S3 by default unless explicitly enabled
# In deployed AgentCore (Lambda), set USE_S3_PERSISTENCE=true
_USE_S3_PERSISTENCE_ENV = os.environ.get("USE_S3_PERSISTENCE", "false").lower()
_USE_S3_PERSISTENCE = _USE_S3_PERSISTENCE_ENV == "true"

print(f"[AgentCore] USE_S3_PERSISTENCE={_USE_S3_PERSISTENCE} (from env: {_USE_S3_PERSISTENCE_ENV})")

# Initialize S3 client (only if persistence enabled)
_s3_client = None
if _USE_S3_PERSISTENCE:
    print("[AgentCore] Initializing S3 client...")
    try:
        _s3_client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        print("[AgentCore] S3 client initialized successfully")
    except Exception as e:
        print(f"[AgentCore] Failed to initialize S3 client: {e}")
        _s3_client = None
        _USE_S3_PERSISTENCE = False
else:
    print("[AgentCore] S3 persistence disabled (local dev mode)")

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

    def to_dict(self) -> dict[str, Any]:
        """Serialize session state to dictionary (for S3 persistence)."""
        return {
            "session_id": self.session_id,
            "repo": self.repo,
            "story": self.story,
            "model_id": self.model_id,
            "auto_approve": self.auto_approve,
            "pending_stage": self.pending_stage,
            "completed_stages": self.completed_stages,
            "pending_answers": self.pending_answers,
            "pending_feedback": self.pending_feedback,
            "final_result": self.final_result,
            "error": self.error,
            "output_dir": self.output_dir,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "_SessionState":
        """Deserialize session state from dictionary (from S3)."""
        session = _SessionState(
            session_id=data["session_id"],
            repo=data["repo"],
            story=data["story"],
            model_id=data["model_id"],
            auto_approve=data.get("auto_approve", True),
        )
        session.pending_stage = data.get("pending_stage")
        session.completed_stages = data.get("completed_stages", [])
        session.pending_answers = data.get("pending_answers")
        session.pending_feedback = data.get("pending_feedback")
        session.final_result = data.get("final_result")
        session.error = data.get("error")
        return session


# ---------------------------------------------------------------------------
# S3 Session Persistence
# ---------------------------------------------------------------------------

def _save_session_to_s3(session: _SessionState) -> None:
    """Persist session state to S3 for cross-container durability."""
    if not _USE_S3_PERSISTENCE or not _s3_client:
        return

    try:
        key = f"sessions/{session.session_id}.json"
        data = session.to_dict()
        _s3_client.put_object(
            Bucket=_SESSION_BUCKET,
            Key=key,
            Body=json.dumps(data),
            ContentType="application/json",
        )
    except Exception as e:
        # Log but don't fail - fall back to in-memory only
        print(f"Warning: Failed to save session to S3: {e}")


def _load_session_from_s3(session_id: str) -> _SessionState | None:
    """Load session state from S3."""
    if not _USE_S3_PERSISTENCE or not _s3_client:
        return None

    try:
        key = f"sessions/{session_id}.json"
        response = _s3_client.get_object(Bucket=_SESSION_BUCKET, Key=key)
        data = json.loads(response["Body"].read())
        return _SessionState.from_dict(data)
    except _s3_client.exceptions.NoSuchKey:
        return None
    except Exception as e:
        print(f"Warning: Failed to load session from S3: {e}")
        return None


def _delete_session_from_s3(session_id: str) -> None:
    """Delete session state from S3 (cleanup after completion)."""
    if not _USE_S3_PERSISTENCE or not _s3_client:
        return

    try:
        key = f"sessions/{session_id}.json"
        _s3_client.delete_object(Bucket=_SESSION_BUCKET, Key=key)
    except Exception as e:
        # Log but don't fail
        print(f"Warning: Failed to delete session from S3: {e}")


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
        auto_approve=True,  # AgentCore mode: auto-fill questions
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
    # Debug logging to file
    debug_log = Path("/tmp/agentcore_debug.log")

    def log(msg: str) -> None:
        with open(debug_log, "a") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} - {msg}\n")
            f.flush()

    log(f"ENTER _run_workflow_in_background for session {session.session_id}")

    import app.workflow as wf_module

    original_approval = wf_module._request_approval_python
    log("Imported app.workflow")

    def _headless_approval(stage: str, summary: str, target_repo: str = "", auto_approve: bool = False) -> bool:
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

        # Persist updated state to S3 after each stage
        _save_session_to_s3(session)

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

    log("Replaced _request_approval_python with headless version")
    wf_module._request_approval_python = _headless_approval  # type: ignore[attr-defined]

    try:
        log("Building orchestrator...")
        orchestrator = _build_headless_orchestrator(session)

        # In Lambda, /var/task is read-only. Copy repo to /tmp for writing.
        import shutil

        workspace_root = os.environ.get("AIDLC_WORKSPACE_ROOT", "")
        print(f"[AgentCore] AIDLC_WORKSPACE_ROOT={workspace_root}", flush=True)
        if workspace_root == "/var/task":
            # Lambda environment: copy repo from /var/task to /tmp
            # Source: /var/task/kiro-sandbox/services/java-api
            # Dest: /tmp/aidlc-workdir/{session_id}/java-api
            source_repo = Path(f"/var/task/{session.repo}")
            repo_name = source_repo.name  # e.g., "java-api"
            temp_repo = Path(f"/tmp/aidlc-workdir/{session.session_id}/{repo_name}")
            temp_repo.parent.mkdir(parents=True, exist_ok=True)

            print(f"[AgentCore] Copying repo from {source_repo} to {temp_repo}", flush=True)
            log(f"Copying repo from {source_repo} to {temp_repo} (Lambda read-only workaround)")
            if source_repo.exists():
                shutil.copytree(source_repo, temp_repo, dirs_exist_ok=True)
                # Pass absolute path - workflow.py will use it directly since Path(base) / Path(absolute) = absolute
                target_repo_path = str(temp_repo.resolve())
                print(f"[AgentCore] Using working copy: {target_repo_path}", flush=True)
                log(f"Using working copy: {target_repo_path}")
            else:
                print(f"[AgentCore] WARNING: Source repo not found at {source_repo}", flush=True)
                log(f"WARNING: Source repo not found at {source_repo}, using as-is")
                target_repo_path = session.repo
        else:
            # Local/dev environment: use repo path as-is
            target_repo_path = session.repo

        log(f"Starting workflow run() for repo={target_repo_path}")
        result = orchestrator.run(
            target_repo=target_repo_path,
            user_story=session.story,
        )
        log("Workflow run() completed")
        session.final_result = result
    except Exception as exc:
        log(f"Workflow error: {exc}")
        session.error = str(exc)
    finally:
        log("Cleaning up...")
        wf_module._request_approval_python = original_approval  # type: ignore[attr-defined]
        session.pending_stage = "__done__"

        # Save final state to S3 before signaling completion
        _save_session_to_s3(session)

        session.signal_paused()
        log("EXIT _run_workflow_in_background")


# ---------------------------------------------------------------------------
# HTTP entrypoint
# ---------------------------------------------------------------------------

@app.entrypoint
def invoke(payload: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    """
    Main AgentCore invocation handler.

    Actions: start | answer | approve | feedback
    """
    import json as _json
    # agentcore invoke CLI wraps the payload as {"prompt": "<json string>"}
    if "prompt" in payload and "action" not in payload:
        try:
            # The CLI may embed literal newlines in the JSON string; collapse them.
            raw = payload["prompt"].replace("\n", " ").replace("\r", " ")
            payload = _json.loads(raw)
        except (ValueError, TypeError):
            pass

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
            "MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0",
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

        # Persist to S3 for cross-container durability
        _save_session_to_s3(session)

        thread = threading.Thread(
            target=_run_workflow_in_background,
            args=(session,),
            daemon=True,
            name=f"aidlc-{session_id[:8]}",
        )
        session._thread = thread
        thread.start()

        # In auto_approve mode the workflow runs to completion in the background.
        # Return immediately so the HTTP client isn't left waiting for 7+ minutes.
        # The caller can poll with action='approve' to check progress/completion.
        if session.auto_approve:
            return {
                "status": "running",
                "session_id": session_id,
                "stage": "starting",
                "completed_stages": [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Manual mode — wait for the first stage gate before returning.
        session.wait_for_pause(timeout=600.0)
        return _build_response(session)

    # ------------------------------------------------------------------
    # ANSWER / APPROVE / FEEDBACK — resume a paused session
    # ------------------------------------------------------------------
    with _SESSIONS_LOCK:
        session = _ACTIVE_SESSIONS.get(session_id)

    # If not in memory, try loading from S3 (cross-container persistence)
    if session is None:
        session = _load_session_from_s3(session_id)
        if session is not None:
            # Restore to in-memory cache
            with _SESSIONS_LOCK:
                _ACTIVE_SESSIONS[session_id] = session

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

        # Clean up S3 session after completion
        _delete_session_from_s3(session.session_id)

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


# ---------------------------------------------------------------------------
# Local dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run()
