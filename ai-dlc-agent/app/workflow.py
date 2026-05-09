"""WorkflowOrchestrator: top-level workflow entry point for the AI-DLC agent."""

from __future__ import annotations

import json
import os
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agents.construction_agent import build_construction_agent
from app.agents.inception_agent import build_inception_agent
from app.hooks.logging_hook import ToolCallLoggingHook
from app.hooks.token_hook import TokenCountingHook
from app.observability.logger import StructuredLogger
from app.observability.metrics import CloudWatchMetrics

DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"


# ---------------------------------------------------------------------------
# Module-level helpers (no class needed)
# ---------------------------------------------------------------------------

def _print_stage_start(stage: str) -> None:
    """Print a stage-starting indicator."""
    try:
        from rich.console import Console
        Console().print(f"\n[bold cyan]▶  Running stage:[/bold cyan] [yellow]{stage}[/yellow]")
    except ImportError:
        print(f"\n▶  Running stage: {stage}", flush=True)


def _print_skip(stage: str) -> None:
    """Print a stage-skipped indicator."""
    try:
        from rich.console import Console
        Console().print(f"  [dim]⏭  Already complete — skipping:[/dim] [dim]{stage}[/dim]")
    except ImportError:
        print(f"  ⏭  Skipping (already complete): {stage}", flush=True)


def _build_inception_context(target_repo: str) -> str:
    """
    Build inception artifact context to pass to construction stages.
    Reads key files from aidlc-docs/inception/ and returns their full content.
    Also includes the existing source tree structure for brownfield projects.
    """
    aidlc = Path(target_repo) / "aidlc-docs"
    parts = []

    # Detect existing source tree structure (language-agnostic, brownfield).
    repo = Path(target_repo)
    lang_configs = [
        ("Java",       repo / "src" / "main" / "java", "*.java"),
        ("Python",     repo / "src",                   "*.py"),
        ("JavaScript", repo / "src",                   "*.js"),
        ("TypeScript", repo / "src",                   "*.ts"),
    ]
    for lang, src_root, glob_pat in lang_configs:
        if not src_root.exists():
            continue
        src_files = sorted(src_root.rglob(glob_pat))[:20]
        if not src_files:
            continue
        tree_lines = [f"**Existing {lang} source tree (use these exact paths):**"]
        for f in src_files:
            tree_lines.append(f"- `{f.relative_to(repo)}`")
        # For Java, also surface the base package.
        if lang == "Java":
            first_rel = src_files[0].relative_to(src_root)
            pkg_parts = first_rel.parts
            if len(pkg_parts) >= 3:
                base_pkg = ".".join(pkg_parts[:3])
                tree_lines.append(f"\n**Base package: `{base_pkg}`** — all new classes MUST use this package.")
        parts.append("\n".join(tree_lines))
        break  # stop at first language found

    # Key inception artifact files.
    key_files = [
        ("Requirements", aidlc / "inception" / "requirements" / "requirements.md"),
        ("Execution Plan", aidlc / "inception" / "plans" / "execution-plan.md"),
        ("Units of Work", aidlc / "inception" / "application-design" / "unit-of-work.md"),
        ("Application Design", aidlc / "inception" / "application-design" / "components.md"),
        ("User Stories", aidlc / "inception" / "user-stories" / "stories.md"),
    ]

    for label, path in key_files:
        if path.exists():
            content = path.read_text(encoding="utf-8")
            parts.append(f"### {label}\n{content}")

    if not parts:
        return "(No inception artifacts found — proceed with user story as the only input)"

    return "\n\n".join(parts)


def _show_artifact_menu(
    written_files: list[tuple[str, str]],
    target_repo: str,
) -> None:
    """Show a numbered menu to pick an artifact to view, then display its content."""
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        from rich.panel import Panel
        console = Console()

        console.print("\n[bold cyan]Select artifact to view:[/bold cyan]")
        for i, (ftype, fpath) in enumerate(written_files, 1):
            icon = "📄" if ftype == "artifact" else "💻"
            console.print(f"  [cyan]{i})[/cyan] {icon} {fpath}")
        console.print("  [dim]Enter number (or press Enter to skip):[/dim] ", end="")

        try:
            choice = input().strip()
        except (EOFError, KeyboardInterrupt):
            return

        if not choice.isdigit():
            return
        idx = int(choice) - 1
        if not (0 <= idx < len(written_files)):
            return

        ftype, fpath = written_files[idx]
        # Resolve full path.
        if ftype == "artifact":
            full_path = Path(target_repo) / "aidlc-docs" / fpath
            # Also try without aidlc-docs prefix if already absolute.
            if not full_path.exists():
                full_path = Path(fpath) if Path(fpath).is_absolute() else Path(target_repo) / fpath
        else:
            full_path = Path(target_repo) / fpath
            if not full_path.exists():
                full_path = Path(fpath) if Path(fpath).is_absolute() else Path(target_repo) / fpath

        if not full_path.exists():
            console.print(f"[red]File not found: {full_path}[/red]")
            return

        content = full_path.read_text(encoding="utf-8")
        # Show first 3000 chars to avoid flooding the terminal.
        preview = content[:3000] + ("\n\n[dim]... (truncated)[/dim]" if len(content) > 3000 else "")
        console.print(
            Panel(
                Markdown(preview),
                title=f"[bold]{fpath}[/bold]",
                border_style="cyan",
                padding=(1, 2),
            )
        )
    except ImportError:
        print("rich not available — open the file in your editor to review.", flush=True)


def _find_questions_file(target_repo: str) -> "Path | None":
    """Find the requirement-verification-questions.md file, handling path variations."""
    for candidate in [
        Path(target_repo) / "aidlc-docs" / "inception" / "requirements" / "requirement-verification-questions.md",
        Path(target_repo) / "aidlc-docs" / "aidlc-docs" / "inception" / "requirements" / "requirement-verification-questions.md",
    ]:
        if candidate.exists():
            return candidate
    return None


def _run_stage_with_retry(
    agent: Any,
    stage: str,
    abs_target_repo: str,
    user_story: str,
    logger: Any,
    is_construction: bool = False,
    max_retries: int = 2,
    custom_prompt: str | None = None,
) -> Any:
    """
    Run a single stage with retry on transient Bedrock errors.
    Retries on EventStreamError and ReadTimeoutError up to max_retries times.
    """
    import botocore.exceptions

    extra = (
        "Write source code using write_source_file. "
        if is_construction else ""
    )
    prompt = custom_prompt or (
        f"Execute the '{stage}' stage for:\n"
        f"Target repository: {abs_target_repo}\n"
        f"User story: {user_story}\n\n"
        f"Execute ONLY this single stage. Write all artifacts using "
        f"write_aidlc_artifact. {extra}"
        f"Call update_workflow_state when done. "
        f"Do NOT call request_approval — the orchestrator handles approval."
    )

    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            # Reset artifact tracker at the start of each attempt.
            try:
                from app.skills.stage_tracker import reset as _reset_tracker
                _reset_tracker()
            except Exception:
                pass
            return agent(prompt)
        except (botocore.exceptions.EventStreamError,
                botocore.exceptions.ReadTimeoutError,
                Exception) as exc:
            err_str = str(exc)
            # Only retry on known transient errors
            transient = any(kw in err_str for kw in (
                "modelStreamErrorException",
                "Read timed out",
                "ThrottlingException",
                "ServiceUnavailableException",
            ))
            if transient and attempt < max_retries:
                wait = attempt * 5
                try:
                    from rich.console import Console
                    Console().print(
                        f"  [yellow]⚠  Transient error on attempt {attempt}/{max_retries}, "
                        f"retrying in {wait}s...[/yellow]"
                    )
                except ImportError:
                    print(f"  ⚠  Retrying in {wait}s...", flush=True)
                import time as _time
                _time.sleep(wait)
                last_exc = exc
                continue
            raise

    raise last_exc  # type: ignore


def _request_approval_python(stage: str, summary: str, target_repo: str = "") -> bool:
    """
    Python-level approval gate — blocks stdin until the user responds.
    If a requirement-verification-questions.md file exists, displays questions
    interactively and collects answers before asking for approval.
    Returns True if approved, False if rejected.
    """
    import signal
    from app.skills.interactive_questions import run_interactive_questions

    questions_file = _find_questions_file(target_repo) if target_repo else None

    # Get files written during this stage.
    try:
        from app.skills.stage_tracker import get_written
        written_files = get_written()
    except Exception:
        written_files = []

    # Auto-skip approval if no artifacts were written (stage was skipped by agent).
    if not written_files and stage not in ("requirements-analysis",):
        try:
            from rich.console import Console
            Console().print(f"  [dim]⏭  No artifacts written — auto-skipping approval for: {stage}[/dim]")
        except ImportError:
            print(f"  ⏭  No artifacts — skipping: {stage}", flush=True)
        return True
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.markdown import Markdown
        console = Console()

        short = summary[:400] + ("..." if len(summary) > 400 else "")

        # Build artifact list for the panel.
        artifact_lines = ""
        if written_files:
            artifact_lines = "\n\n**Artifacts written:**\n"
            for ftype, fpath in written_files:
                icon = "📄" if ftype == "artifact" else "💻"
                artifact_lines += f"- {icon} `{fpath}`\n"

        console.print(
            Panel(
                Markdown(short + artifact_lines),
                title=f"[bold green]✅  Stage complete: {stage}[/bold green]",
                border_style="green",
                padding=(1, 2),
            )
        )
    except ImportError:
        print(f"\n✅  Stage complete: {stage}", flush=True)
        for ftype, fpath in written_files:
            print(f"  {'📄' if ftype == 'artifact' else '💻'} {fpath}", flush=True)

    # Show interactive questions ONLY for requirements-analysis stage.
    # All other stages skip the questions panel.
    if questions_file and stage == "requirements-analysis":
        completed = run_interactive_questions(questions_file)
        if not completed:
            return False  # User aborted

    try:
        from rich.console import Console
        Console().print(
            "\n[bold]Press [green]Enter[/green] to continue, "
            "type [cyan]v[/cyan] to view an artifact, "
            "or type feedback to request changes:[/bold]"
        )
    except ImportError:
        print("\nPress Enter to continue (v=view artifact, or type feedback):", flush=True)

    def _timeout(signum: int, frame: object) -> None:
        raise TimeoutError()

    old = signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(300)
    try:
        response = input().strip()
    except TimeoutError:
        response = ""
    except EOFError:
        response = ""
    except KeyboardInterrupt:
        print()
        response = ""
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)

    # Handle "v" or "view" — show artifact content then ask again.
    if response.lower() in ("v", "view") and written_files:
        _show_artifact_menu(written_files, target_repo)
        # Ask again after viewing.
        try:
            from rich.console import Console
            Console().print("\n[bold]Press [green]Enter[/green] to continue, or type feedback:[/bold]")
        except ImportError:
            print("Press Enter to continue:", flush=True)
        old2 = signal.signal(signal.SIGALRM, _timeout)
        signal.alarm(300)
        try:
            response = input().strip()
        except (TimeoutError, EOFError, KeyboardInterrupt):
            response = ""
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old2)

    return response.lower() in ("approve", "yes", "continue", "y", "ok", "", "skip")


# Resolve rules path relative to the workspace root (parent of ai-dlc-agent/).
# __file__ = .../ai-dlc-agent/app/workflow.py
# .parent       = .../ai-dlc-agent/app/
# .parent.parent = .../ai-dlc-agent/
# .parent.parent.parent = workspace root (aws-sagents-dlc/)
_WORKSPACE_ROOT = Path(__file__).parent.parent.parent.resolve()
RULES_BASE_PATH = str(_WORKSPACE_ROOT / ".kiro/aws-aidlc-rule-details")


class WorkflowOrchestrator:
    """
    Top-level orchestrator for the AI-DLC Strands Agent.

    Accepts a target repository path and a user story, then executes the full
    AI-DLC workflow (Inception → Construction) by driving Inception_Agent and
    Construction_Agent sequentially with a human approval gate between each stage.
    All planning artifacts are written to ``{target_repo}/aidlc-docs/``
    and all generated source code is written to ``{target_repo}/src/``.

    Args:
        model_id: Amazon Bedrock model identifier.
        output_dir: Directory for session state checkpoints and trace logs.
        rules_base_path: Path to the AI-DLC rule-details directory.
    """

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        output_dir: str = "outputs",
        rules_base_path: str = RULES_BASE_PATH,
    ) -> None:
        self.model_id = model_id
        self.output_dir = output_dir
        self.rules_base_path = rules_base_path

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        self._logger = StructuredLogger(
            log_file=str(Path(output_dir) / "agent_trace.jsonl")
        )
        self._token_hook = TokenCountingHook()
        self._metrics = CloudWatchMetrics(
            region=os.environ.get("AWS_REGION", "us-east-1")
        )

        self.shared_state: dict[str, Any] = {}

    def run(self, target_repo: str, user_story: str) -> dict[str, Any]:
        """
        Execute the full AI-DLC workflow for the given target repo and user story.

        1. Checks ``{target_repo}/aidlc-docs/aidlc-state.md`` for session resumption.
        2. Connects to the MCP filesystem server (falls back to direct I/O on failure).
        3. Builds Inception_Agent and Construction_Agent.
        4. Runs each stage sequentially with a human approval gate between stages.
        5. Checkpoints state to ``outputs/session_state.json`` after completion.
        6. Publishes session metrics to CloudWatch.

        Args:
            target_repo: Path to the target repository (e.g.,
                ``kiro-sandbox/services/java-api``).
            user_story: The user story to implement (e.g.,
                ``"As a user, I want to reset my password"``).

        Returns:
            Consolidated result dictionary containing inception artifacts,
            construction artifacts, session metrics, and optionally an "error" key.
        """
        # Resolve target_repo to an absolute path so agents always use absolute paths.
        abs_target_repo = str((_WORKSPACE_ROOT / target_repo).resolve())

        self.shared_state = {
            "target_repo": abs_target_repo,
            "user_story": user_story,
            "project_type": "unknown",
            "inception": {
                "status": "not_started",
                "completed_stages": [],
                "artifact_paths": {},
                "duration_ms": 0.0,
            },
            "construction": {
                "status": "not_started",
                "completed_stages": [],
                "artifact_paths": {},
                "source_files_written": [],
                "duration_ms": 0.0,
            },
            "session_metrics": {
                "total_tool_calls": 0,
                "total_retries": 0,
                "total_tokens": 0,
                "total_duration_ms": 0.0,
                "total_stages_completed": 0,
            },
        }

        # Check for existing session state (resumption).
        resumption_info = self._check_resumption(target_repo)
        if resumption_info:
            self._logger.log({
                "type": "resumption",
                "message": f"Resuming from stage: {resumption_info.get('last_completed_stage')}",
                "completed_stages": resumption_info.get("completed_stages", []),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        workflow_start = time.monotonic()

        # Connect to MCP filesystem server.
        try:
            mcp_tools = self._get_mcp_tools()
        except Exception as exc:
            self._logger.log({
                "type": "warning",
                "message": f"MCP server unavailable, using fallback tools: {exc}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            mcp_tools = []

        # Build shared hooks.
        logging_hook = ToolCallLoggingHook(
            agent_name="workflow_orchestrator", logger=self._logger
        )
        hooks = [logging_hook, self._token_hook]

        try:
            # Build sub-agents.
            inception_agent = build_inception_agent(
                model_id=self.model_id,
                mcp_tools=mcp_tools,
                shared_state=self.shared_state,
                hooks=hooks,
                rules_base_path=self.rules_base_path,
            )
            construction_agent = build_construction_agent(
                model_id=self.model_id,
                mcp_tools=mcp_tools,
                shared_state=self.shared_state,
                hooks=hooks,
                rules_base_path=self.rules_base_path,
            )

            # --- INCEPTION PHASE ---
            # Run one stage at a time. Python controls the approval gate between stages.
            inception_start = time.monotonic()
            inception_stages = [
                "workspace-detection",
                "reverse-engineering",
                "requirements-analysis",
                "user-stories",
                "workflow-planning",
                "application-design",
                "units-generation",
            ]

            # Determine which stages are already complete.
            completed = self._get_completed_stages(abs_target_repo)

            for stage in inception_stages:
                if stage in completed:
                    _print_skip(stage)
                    continue

                _print_stage_start(stage)
                stage_result = _run_stage_with_retry(
                    agent=inception_agent,
                    stage=stage,
                    abs_target_repo=abs_target_repo,
                    user_story=user_story,
                    logger=self._logger,
                )

                # After requirements-analysis, ensure the questions file was written.
                # If the agent skipped it, ask it to generate the file explicitly.
                if stage == "requirements-analysis":
                    q_path = _find_questions_file(abs_target_repo)
                    if not q_path:
                        try:
                            from rich.console import Console
                            Console().print(
                                "  [yellow]⚠  Questions file not found — requesting generation...[/yellow]"
                            )
                        except ImportError:
                            print("  ⚠  Requesting questions file generation...", flush=True)
                        _run_stage_with_retry(
                            agent=inception_agent,
                            stage="requirements-analysis-questions",
                            abs_target_repo=abs_target_repo,
                            user_story=user_story,
                            logger=self._logger,
                            custom_prompt=(
                                f"Generate the requirement-verification-questions.md file for:\n"
                                f"Target repository: {abs_target_repo}\n"
                                f"User story: {user_story}\n\n"
                                f"Read the existing requirements from "
                                f"{abs_target_repo}/aidlc-docs/inception/requirements/requirements.md "
                                f"and generate 5-8 clarifying questions with lettered options (A, B, C, D).\n\n"
                                f"IMPORTANT: The FIRST question must always be about implementation complexity:\n"
                                f"### Question 1\n"
                                f"What is the target implementation complexity?\n"
                                f"A) PoC / MVP — simplest possible implementation, minimal dependencies\n"
                                f"B) Standard — production-ready but straightforward\n"
                                f"C) Enterprise — full security, scalability, observability, compliance\n"
                                f"D) Other (describe)\n"
                                f"[Answer]: \n\n"
                                f"The remaining questions should adapt based on the user story context.\n"
                                f"Write the file to: inception/requirements/requirement-verification-questions.md\n"
                                f"Use write_aidlc_artifact with target_repo='{abs_target_repo}' and "
                                f"relative_path='inception/requirements/requirement-verification-questions.md'.\n"
                                f"Do NOT call update_workflow_state — just write the questions file."
                            ),
                        )

                # Python-level approval gate — reliable stdin blocking.
                approved = _request_approval_python(stage, str(stage_result), abs_target_repo)
                if not approved:
                    self._logger.log({"type": "stage_rejected", "stage": stage,
                                      "timestamp": datetime.now(timezone.utc).isoformat()})
                    break

                # Check if workflow-planning says to skip remaining stages.
                if stage == "workflow-planning":
                    completed = self._get_completed_stages(abs_target_repo)

            inception_duration_ms = (time.monotonic() - inception_start) * 1000
            self.shared_state["inception"]["status"] = "complete"
            self.shared_state["inception"]["duration_ms"] = round(inception_duration_ms, 2)
            self._checkpoint_state()

            # --- CONSTRUCTION PHASE ---
            construction_start = time.monotonic()
            construction_stages = [
                "functional-design",
                "nfr-requirements",
                "nfr-design",
                "infrastructure-design",
                "code-generation",
                "build-and-test",
            ]

            # Build inception context summary to pass to every construction stage.
            inception_context = _build_inception_context(abs_target_repo)

            completed = self._get_completed_stages(abs_target_repo)

            for stage in construction_stages:
                if stage in completed:
                    _print_skip(stage)
                    continue

                _print_stage_start(stage)

                # For code-generation, add explicit instruction to write source files.
                code_gen_hint = ""
                if stage == "code-generation":
                    code_gen_hint = (
                        "\n\nCRITICAL: You MUST write actual source code files using "
                        "write_source_file. Do NOT skip code generation because of missing "
                        "prerequisites — use the inception artifacts above as your design input. "
                        "Write at minimum the main service/module and entry point for the feature."
                    )

                stage_result = _run_stage_with_retry(
                    agent=construction_agent,
                    stage=stage,
                    abs_target_repo=abs_target_repo,
                    user_story=user_story,
                    logger=self._logger,
                    is_construction=True,
                    custom_prompt=(
                        f"Execute the '{stage}' stage for:\n"
                        f"Target repository: {abs_target_repo}\n"
                        f"User story: {user_story}\n\n"
                        f"INCEPTION PHASE CONTEXT:\n{inception_context}\n\n"
                        f"Execute ONLY this single stage. Write all planning artifacts using "
                        f"write_aidlc_artifact. Write source code using write_source_file. "
                        f"Call update_workflow_state when done. "
                        f"Do NOT call request_approval — the orchestrator handles approval."
                        f"{code_gen_hint}"
                    ),
                )

                # After code-generation, verify source files were actually written.
                if stage == "code-generation":
                    from app.skills.stage_tracker import get_written
                    source_files = [f for t, f in get_written() if t == "source"]
                    if not source_files:
                        try:
                            from rich.console import Console
                            Console().print(
                                "  [yellow]⚠  No source files written — retrying code generation...[/yellow]"
                            )
                        except ImportError:
                            print("  ⚠  No source files — retrying code generation...", flush=True)
                        _run_stage_with_retry(
                            agent=construction_agent,
                            stage="code-generation-retry",
                            abs_target_repo=abs_target_repo,
                            user_story=user_story,
                            logger=self._logger,
                            is_construction=True,
                            custom_prompt=(
                                f"Generate source code for the user story: {user_story}\n"
                                f"Target repository: {abs_target_repo}\n\n"
                                f"INCEPTION CONTEXT:\n{inception_context}\n\n"
                                f"You MUST write source files using write_source_file. "
                                f"The existing source tree is shown in the inception context above — "
                                f"use the EXACT same language, structure, and directory paths. "
                                f"Do NOT introduce new packages or modules outside the existing structure.\n\n"
                                f"At minimum, create the main service/module and any required entry points "
                                f"for the feature described in the user story.\n\n"
                                f"3. Any required DTOs or model updates\n\n"
                                f"Use write_source_file with target_repo='{abs_target_repo}' and "
                                f"relative_path matching the existing source tree structure shown above.\n"
                                f"Do NOT call update_workflow_state or request_approval."
                            ),
                        )

                approved = _request_approval_python(stage, str(stage_result), abs_target_repo)
                if not approved:
                    self._logger.log({"type": "stage_rejected", "stage": stage,
                                      "timestamp": datetime.now(timezone.utc).isoformat()})
                    break

            construction_duration_ms = (time.monotonic() - construction_start) * 1000
            self.shared_state["construction"]["status"] = "complete"
            self.shared_state["construction"]["duration_ms"] = round(construction_duration_ms, 2)
            self._checkpoint_state()

            # Collect token usage from both agents.
            total_input = 0
            total_output = 0
            for agent in (inception_agent, construction_agent):
                try:
                    usage = agent.event_loop_metrics.accumulated_usage
                    total_input += int(usage.get("inputTokens", 0))
                    total_output += int(usage.get("outputTokens", 0))
                except Exception:
                    pass
            if total_input == 0 and total_output == 0:
                total_input = self._token_hook.input_tokens
                total_output = self._token_hook.output_tokens
            self.shared_state["session_metrics"]["input_tokens"] = total_input
            self.shared_state["session_metrics"]["output_tokens"] = total_output
            self.shared_state["session_metrics"]["total_tokens"] = total_input + total_output

        except Exception as exc:
            self._logger.log({
                "type": "error",
                "phase": "workflow",
                "message": str(exc),
                "traceback": traceback.format_exc(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            self._checkpoint_state()
            return self._build_result(
                error=f"Workflow failed: {exc}",
                total_duration_ms=(time.monotonic() - workflow_start) * 1000,
            )

        total_duration_ms = (time.monotonic() - workflow_start) * 1000
        result = self._build_result(total_duration_ms=total_duration_ms)

        self._checkpoint_state()
        self._metrics.publish_session_metrics(result["session_metrics"])

        return result

    def _check_resumption(self, target_repo: str) -> dict | None:
        """
        Check if a previous session exists and return its state.

        Returns:
            The parsed state dict if ``aidlc-state.md`` exists and is valid,
            or None if starting fresh.
        """
        import re

        state_path = Path(target_repo) / "aidlc-docs" / "aidlc-state.md"
        if not state_path.exists():
            return None

        try:
            text = state_path.read_text(encoding="utf-8")
            match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
            if match:
                state = json.loads(match.group(1))
                if state.get("last_completed_stage"):
                    return state
        except (OSError, json.JSONDecodeError):
            pass

        return None

    def _get_completed_stages(self, target_repo: str) -> list[str]:
        """Read completed stages from aidlc-state.md."""
        import re
        state_path = Path(target_repo) / "aidlc-docs" / "aidlc-state.md"
        if not state_path.exists():
            return []
        try:
            text = state_path.read_text(encoding="utf-8")
            match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
            if match:
                state = json.loads(match.group(1))
                return state.get("completed_stages", [])
        except (OSError, json.JSONDecodeError):
            pass
        return []

    def _get_mcp_tools(self) -> list:
        """
        Connect to the MCP filesystem server and return its tools.

        The server is scoped to the workspace root (covering both the rule-details
        directory and the target repo). Returns an empty list on failure.
        """
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            import asyncio

            async def _list_tools() -> list:
                server_params = StdioServerParameters(
                    command="uvx",
                    args=["mcp-server-filesystem", "."],
                )
                async with stdio_client(server_params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools_result = await session.list_tools()
                        return tools_result.tools if hasattr(tools_result, "tools") else []

            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_list_tools())
            finally:
                loop.close()

        except Exception:
            return []

    def _checkpoint_state(self) -> None:
        """Serialize shared_state to outputs/session_state.json."""
        checkpoint_path = Path(self.output_dir) / "session_state.json"
        try:
            with open(checkpoint_path, "w", encoding="utf-8") as fh:
                json.dump(self.shared_state, fh, indent=2, default=str)
        except OSError as exc:
            self._logger.log({
                "type": "warning",
                "message": f"Could not write checkpoint: {exc}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    def _build_result(
        self,
        error: str | None = None,
        total_duration_ms: float = 0.0,
    ) -> dict[str, Any]:
        """Assemble the consolidated result dictionary."""
        # Use already-populated token counts if available, otherwise fall back to hook.
        metrics = self.shared_state["session_metrics"]
        if metrics.get("total_tokens", 0) == 0:
            metrics["total_tokens"] = self._token_hook.total_tokens
            metrics["input_tokens"] = self._token_hook.input_tokens
            metrics["output_tokens"] = self._token_hook.output_tokens
        metrics["total_duration_ms"] = round(total_duration_ms, 2)

        result: dict[str, Any] = {
            "target_repo": self.shared_state.get("target_repo", ""),
            "user_story": self.shared_state.get("user_story", ""),
            "inception": self.shared_state.get("inception", {}),
            "construction": self.shared_state.get("construction", {}),
            "session_metrics": metrics,
        }
        if error:
            result["error"] = error
        return result
