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

DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
DEFAULT_MAX_OUTPUT_TOKENS = 8192


def _max_output_tokens() -> int:
    """Bedrock max output tokens per model turn (override via AIDLC_MAX_OUTPUT_TOKENS)."""
    raw = os.environ.get("AIDLC_MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS))
    try:
        return max(1024, int(raw))
    except ValueError:
        return DEFAULT_MAX_OUTPUT_TOKENS


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


def _count_repo_source_files(target_repo: str) -> int:
    """Count application source files under the target repo (excludes aidlc-docs, etc.)."""
    root = Path(target_repo)
    if not root.is_dir():
        return 0
    skip_dirs = {
        "aidlc-docs",
        ".git",
        ".venv",
        "node_modules",
        "__pycache__",
        "chart",
        ".workspaces",
    }
    extensions = {".py", ".java", ".ts", ".js", ".go", ".kt", ".rb"}
    count = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in extensions:
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        count += 1
    return count


def _reverse_engineering_artifact_paths(abs_target_repo: str) -> list[str]:
    """
    Relative paths under aidlc-docs/ to produce during reverse-engineering.

    All 9 artifacts are REQUIRED for brownfield cost optimization, regardless of repo size.
    Without code-structure.md and api-documentation.md, the code-generation stage cannot
    check if features already exist, leading to $4-10 wasted per workflow.
    """
    return [
        "inception/reverse-engineering/business-overview.md",
        "inception/reverse-engineering/architecture.md",
        "inception/reverse-engineering/code-structure.md",
        "inception/reverse-engineering/api-documentation.md",
        "inception/reverse-engineering/component-inventory.md",
        "inception/reverse-engineering/technology-stack.md",
        "inception/reverse-engineering/dependencies.md",
        "inception/reverse-engineering/code-quality-assessment.md",
        "inception/reverse-engineering/reverse-engineering-timestamp.md",
    ]


def _prompt_reverse_engineering_artifact(
    abs_target_repo: str,
    user_story: str,
    relative_path: str,
    *,
    first_turn: bool,
) -> str:
    """One artifact per model turn to stay within max_tokens output limit."""
    read_step = (
        "1. Call load_rule_file(stage_name=\"reverse-engineering\") and skim scope.\n"
        "2. Use scan_directory and file_read on key entrypoints only (not the whole tree).\n"
    ) if first_turn else (
        "1. Use file_read only if you still need context from the previous turn.\n"
    )
    return (
        f"Execute the 'reverse-engineering' stage for:\n"
        f"Target repository: {abs_target_repo}\n"
        f"User story: {user_story}\n\n"
        f"OUTPUT LIMIT: Use exactly ONE write_aidlc_artifact call in this turn.\n"
        f"Keep the file concise (aim for under 120 lines). Use bullets; avoid huge diagrams.\n\n"
        f"{read_step}"
        f"3. Write ONLY this file with write_aidlc_artifact:\n"
        f"   relative_path=\"{relative_path}\"\n"
        f"4. Do NOT call update_workflow_state yet.\n"
        f"5. Do NOT call request_approval.\n"
        f"6. Do NOT write any other artifacts in this turn."
    )


def _prompt_reverse_engineering_complete(abs_target_repo: str) -> str:
    return (
        f"Reverse-engineering artifacts for {abs_target_repo} are written.\n"
        f"Call update_workflow_state(target_repo=\"{abs_target_repo}\", "
        f"stage_name=\"reverse-engineering\", status=\"complete\") ONLY.\n"
        f"Do not write files or call request_approval."
    )


def _run_reverse_engineering_stage(
    agent: Any,
    abs_target_repo: str,
    user_story: str,
    logger: Any,
) -> Any:
    """
    Run reverse-engineering as multiple agent turns (one artifact per turn).

    Prevents MaxTokensReachedException from batching many large write_aidlc_artifact
    tool calls in a single model response.
    """
    last_result: Any = None
    paths = _reverse_engineering_artifact_paths(abs_target_repo)
    for i, rel_path in enumerate(paths):
        last_result = _run_stage_with_retry(
            agent=agent,
            stage="reverse-engineering",
            abs_target_repo=abs_target_repo,
            user_story=user_story,
            logger=logger,
            custom_prompt=_prompt_reverse_engineering_artifact(
                abs_target_repo,
                user_story,
                rel_path,
                first_turn=(i == 0),
            ),
        )
    return _run_stage_with_retry(
        agent=agent,
        stage="reverse-engineering",
        abs_target_repo=abs_target_repo,
        user_story=user_story,
        logger=logger,
        custom_prompt=_prompt_reverse_engineering_complete(abs_target_repo),
    ) or last_result


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
            if "max_tokens" in err_str.lower() and attempt < max_retries:
                wait = attempt * 5
                try:
                    from rich.console import Console
                    Console().print(
                        f"  [yellow]⚠  Output token limit hit — retrying '{stage}' "
                        f"with a smaller scope (attempt {attempt + 1}/{max_retries})...[/yellow]"
                    )
                except ImportError:
                    print(
                        f"  ⚠  max_tokens limit — retrying {stage} "
                        f"(attempt {attempt + 1}/{max_retries})...",
                        flush=True,
                    )
                prompt = (
                    f"Continue stage '{stage}' for {abs_target_repo}.\n"
                    f"Your previous response exceeded the output token limit.\n"
                    f"Use at most ONE write_aidlc_artifact call with concise content "
                    f"(under 80 lines). Then update_workflow_state if this stage is complete.\n"
                    f"User story context: {user_story}"
                )
                time.sleep(wait)
                continue
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


def _request_approval_python(stage: str, summary: str, target_repo: str = "", auto_approve: bool = False) -> bool:
    """
    Python-level approval gate — blocks stdin until the user responds.
    If a requirement-verification-questions.md file exists, displays questions
    interactively and collects answers before asking for approval.
    Returns True if approved, False if rejected.

    Args:
        stage: Stage name
        summary: Stage summary text
        target_repo: Target repository path
        auto_approve: If True, skip approval prompts and return True immediately
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

    # If auto-approve mode, skip interactive approval.
    if auto_approve:
        try:
            from rich.console import Console
            Console().print(f"  [dim]✓  Auto-approved: {stage}[/dim]")
        except ImportError:
            print(f"  ✓  Auto-approved: {stage}", flush=True)
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

    # For requirements-analysis: show questions AFTER the user types 'v',
    # or immediately if they press Enter (no artifact to view).
    # For all other stages: 'v' opens the artifact menu.

    hint = (
        "\n[bold]Press [green]Enter[/green] to answer clarifying questions, "
        "type [cyan]v[/cyan] to view an artifact first, "
        "or type feedback to request changes:[/bold]"
        if (questions_file and stage == "requirements-analysis")
        else
        "\n[bold]Press [green]Enter[/green] to continue, "
        "type [cyan]v[/cyan] to view an artifact, "
        "or type feedback to request changes:[/bold]"
    )
    try:
        from rich.console import Console
        Console().print(hint)
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

    # Handle "v" or "view" — show artifact menu (or questions file) then ask again.
    if response.lower() in ("v", "view"):
        if written_files:
            _show_artifact_menu(written_files, target_repo)
        elif questions_file and stage == "requirements-analysis":
            # No tracked artifacts but questions file exists — show it directly.
            try:
                content = questions_file.read_text(encoding="utf-8")
                from rich.console import Console
                from rich.panel import Panel
                from rich.markdown import Markdown
                Console().print(
                    Panel(
                        Markdown(content[:3000] + ("\n\n*(truncated)*" if len(content) > 3000 else "")),
                        title="[bold cyan]📋  requirement-verification-questions.md[/bold cyan]",
                        border_style="cyan",
                        padding=(1, 2),
                    )
                )
            except Exception:
                pass

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

    # For requirements-analysis: run interactive questions if approved/continuing.
    if questions_file and stage == "requirements-analysis":
        if response.lower() in ("approve", "yes", "continue", "y", "ok", "", "skip"):
            completed = run_interactive_questions(questions_file)
            if not completed:
                return False  # User aborted
            return True

    return response.lower() in ("approve", "yes", "continue", "y", "ok", "", "skip")


# Resolve rules path: env var override takes priority, then look for kiro_rules/
# bundled alongside the app package (container), then fall back to workspace root.
_AGENT_DIR = Path(__file__).parent.parent.resolve()  # .../ai-dlc-agent/
_WORKSPACE_ROOT = _AGENT_DIR.parent.resolve()         # .../aws-sagents-dlc/
if "AIDLC_RULES_PATH" in os.environ and os.environ["AIDLC_RULES_PATH"]:
    RULES_BASE_PATH = str(Path(os.environ["AIDLC_RULES_PATH"]))
elif (_AGENT_DIR / "kiro_rules/aws-aidlc-rule-details").exists():
    RULES_BASE_PATH = str(_AGENT_DIR / "kiro_rules/aws-aidlc-rule-details")
else:
    RULES_BASE_PATH = str(_WORKSPACE_ROOT / ".kiro/aws-aidlc-rule-details")


def _get_units_of_work(target_repo: str) -> list[dict[str, str]]:
    """
    Parse unit-of-work.md to extract units for per-unit construction loop.

    Returns list of unit dicts with 'name' and 'description' keys.
    If no units file exists or parsing fails, returns single default unit.
    """
    uow_path = (
        Path(target_repo) / "aidlc-docs" / "inception" / "application-design" / "unit-of-work.md"
    )

    if not uow_path.exists():
        # No units file - treat entire project as single unit
        return [{"name": "default", "description": "Single unit of work (no decomposition)"}]

    try:
        content = uow_path.read_text(encoding="utf-8")
        units = []

        # Parse ONLY numbered unit sections: "## Unit-1:" or "## Unit 1:" or "### Service-2:"
        # Do NOT match generic section headings like "## Unit Responsibilities"
        import re
        for match in re.finditer(
            r"(?:##|###)\s+(?:Unit|Service|Module)[-\s]*(\d+)\s*:\s+(.+?)(?:\n|$)",
            content,
            re.IGNORECASE
        ):
            unit_number = match.group(1)
            name = match.group(2).strip()
            # Try to find description in next few lines
            desc_start = match.end()
            desc_end = content.find("\n##", desc_start)
            if desc_end == -1:
                desc_end = desc_start + 500
            desc_block = content[desc_start:desc_end].strip()
            # Take first paragraph as description
            desc = desc_block.split("\n\n")[0].strip()[:200]
            if name:
                units.append({"name": name, "description": desc or f"Unit {unit_number}: {name}"})

        if units:
            return units
    except Exception:
        pass

    # Fallback to single unit
    return [{"name": "default", "description": "Single unit of work"}]


def _get_skipped_stages(target_repo: str) -> set[str]:
    """
    Parse the execution plan to find stages explicitly marked SKIP.

    Reads ``{target_repo}/aidlc-docs/inception/plans/execution-plan.md`` and
    looks for lines matching the pattern ``**Stage Name** - SKIP``.
    Returns a set of orchestrator stage keys to skip.
    """
    plan_path = (
        Path(target_repo) / "aidlc-docs" / "inception" / "plans" / "execution-plan.md"
    )
    if not plan_path.exists():
        return set()

    # Map plan text fragments (lowercase, no markdown) → orchestrator stage keys
    _STAGE_MAP = {
        "application design":     "application-design",
        "units generation":       "units-generation",
        "units planning":         "units-generation",   # alternate label
        "functional design":      "functional-design",
        "nfr requirements":       "nfr-requirements",
        "nfr design":             "nfr-design",
        "infrastructure design":  "infrastructure-design",
        "user stories":           "user-stories",
    }

    skipped: set[str] = set()
    try:
        import re
        text = plan_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            # Match lines like: - [ ] **Application Design** - SKIP
            # or Mermaid nodes:  AD["Application Design<br/><b>SKIP</b>"]
            if "skip" not in line.lower():
                continue
            # Strip markdown bold markers and HTML tags, lowercase
            clean = re.sub(r"\*\*|<[^>]+>", "", line).lower()
            for fragment, stage_key in _STAGE_MAP.items():
                if fragment in clean:
                    skipped.add(stage_key)
    except OSError:
        pass

    return skipped


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
        auto_approve: If True (AgentCore mode), auto-fill clarifying questions.
                     If False (CLI mode), display questions interactively.
    """

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        output_dir: str = "outputs",
        rules_base_path: str = RULES_BASE_PATH,
        auto_approve: bool = False,
    ) -> None:
        self.model_id = model_id
        self.output_dir = output_dir
        self.rules_base_path = rules_base_path
        self.auto_approve = auto_approve
        self.max_output_tokens = _max_output_tokens()

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
        resumption_info = self._check_resumption(abs_target_repo)
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
            # --- INCEPTION PHASE ---
            # Build a fresh agent per stage to keep conversation history minimal.
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
            # Stages the execution plan says to skip (populated after workflow-planning).
            plan_skips: set[str] = _get_skipped_stages(abs_target_repo)

            for stage in inception_stages:
                if stage in completed:
                    _print_skip(stage)
                    continue

                if stage in plan_skips:
                    _print_skip(f"{stage} (plan: SKIP)")
                    continue

                _print_stage_start(stage)

                # Fresh agent per stage — no accumulated conversation history.
                inception_agent = build_inception_agent(
                    model_id=self.model_id,
                    mcp_tools=mcp_tools,
                    shared_state=self.shared_state,
                    hooks=hooks,
                    rules_base_path=self.rules_base_path,
                    max_output_tokens=self.max_output_tokens,
                    auto_approve=self.auto_approve,
                )

                if stage == "reverse-engineering":
                    stage_result = _run_reverse_engineering_stage(
                        agent=inception_agent,
                        abs_target_repo=abs_target_repo,
                        user_story=user_story,
                        logger=self._logger,
                    )
                else:
                    stage_result = _run_stage_with_retry(
                        agent=inception_agent,
                        stage=stage,
                        abs_target_repo=abs_target_repo,
                        user_story=user_story,
                        logger=self._logger,
                    )

                # After reverse-engineering, validate that ALL 9 required artifacts were written.
                # If any are missing, fail the stage with clear error message.
                if stage == "reverse-engineering":
                    re_dir = Path(abs_target_repo) / "aidlc-docs/inception/reverse-engineering"
                    required_artifacts = [
                        "business-overview.md",
                        "architecture.md",
                        "code-structure.md",
                        "api-documentation.md",
                        "component-inventory.md",
                        "technology-stack.md",
                        "dependencies.md",
                        "code-quality-assessment.md",
                        "reverse-engineering-timestamp.md",
                    ]
                    missing = [f for f in required_artifacts if not (re_dir / f).exists()]
                    if missing:
                        try:
                            from rich.console import Console
                            Console().print(
                                f"\n[red]❌ REVERSE-ENGINEERING VALIDATION FAILED[/red]\n\n"
                                f"[yellow]Missing {len(missing)}/{len(required_artifacts)} required artifacts:[/yellow]\n"
                                + "\n".join(f"  • {f}" for f in missing) + "\n\n"
                                f"[dim]These files are REQUIRED for brownfield cost optimization.[/dim]\n"
                                f"[dim]Without them, code-generation will waste $4-10 per workflow.[/dim]\n\n"
                                f"[yellow]Agent wrote: {list((re_dir).glob('*.md')) if re_dir.exists() else 'No files'}[/yellow]\n"
                            )
                        except ImportError:
                            print(f"\n❌ VALIDATION FAILED: Missing {len(missing)} artifacts: {missing}\n", flush=True)
                        raise ValueError(
                            f"Reverse-engineering stage failed validation: "
                            f"Missing {len(missing)}/{len(required_artifacts)} required artifacts: {missing}. "
                            f"Agent must write ALL 9 artifacts, not just summary.md. "
                            f"Update .kiro/aws-aidlc-rule-details/inception/reverse-engineering.md if needed."
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
                approved = _request_approval_python(stage, str(stage_result), abs_target_repo, self.auto_approve)
                if not approved:
                    self._logger.log({"type": "stage_rejected", "stage": stage,
                                      "timestamp": datetime.now(timezone.utc).isoformat()})
                    break

                # Ensure stage is recorded as complete (agent may not have called update_workflow_state).
                from app.skills.update_workflow_state import update_workflow_state
                completed_check = self._get_completed_stages(abs_target_repo)
                if stage not in completed_check:
                    update_workflow_state(target_repo=abs_target_repo, stage_name=stage, status="complete")

                # After workflow-planning, read the execution plan to find stages to skip.
                if stage == "workflow-planning":
                    completed = self._get_completed_stages(abs_target_repo)
                    plan_skips = _get_skipped_stages(abs_target_repo)
                    if plan_skips:
                        try:
                            from rich.console import Console
                            Console().print(
                                f"  [dim]📋  Execution plan: skipping {', '.join(sorted(plan_skips))}[/dim]"
                            )
                        except ImportError:
                            print(f"  📋  Skipping per plan: {', '.join(sorted(plan_skips))}", flush=True)

            inception_duration_ms = (time.monotonic() - inception_start) * 1000
            self.shared_state["inception"]["status"] = "complete"
            self.shared_state["inception"]["duration_ms"] = round(inception_duration_ms, 2)
            self._checkpoint_state()

            # --- CONSTRUCTION PHASE ---
            construction_start = time.monotonic()

            # Per-unit stages (run once per unit)
            per_unit_stages = [
                "functional-design",
                "nfr-requirements",
                "nfr-design",
                "infrastructure-design",
                "code-generation",
            ]

            # Post-unit stage (runs once after all units)
            post_unit_stage = "build-and-test"

            # Build inception context summary to pass to every construction stage.
            inception_context = _build_inception_context(abs_target_repo)

            # Get units of work from inception phase
            units = _get_units_of_work(abs_target_repo)

            try:
                from rich.console import Console
                Console().print(
                    f"\n[bold cyan]📦  Construction Phase:[/bold cyan] "
                    f"[yellow]{len(units)} unit(s) of work[/yellow]"
                )
                for idx, unit in enumerate(units, 1):
                    Console().print(f"  [dim]{idx}. {unit['name']}[/dim]")
            except ImportError:
                print(f"\n📦  Construction: {len(units)} unit(s)", flush=True)

            completed = self._get_completed_stages(abs_target_repo)
            # Re-read plan skips — execution plan is now fully written.
            plan_skips = _get_skipped_stages(abs_target_repo)

            # Optimization: For single-unit projects, skip unit-level tracking overhead
            # Use simple stage names instead of "stage-unit-1" to reduce complexity
            single_unit_mode = (len(units) == 1)

            # Per-unit construction loop
            for unit_idx, unit in enumerate(units, 1):
                unit_name = unit["name"]
                unit_desc = unit["description"]

                # Only show unit header for multi-unit projects
                if not single_unit_mode:
                    try:
                        from rich.console import Console
                        Console().print(
                            f"\n[bold magenta]▶  Unit {unit_idx}/{len(units)}:[/bold magenta] "
                            f"[cyan]{unit_name}[/cyan]"
                        )
                    except ImportError:
                        print(f"\n▶  Unit {unit_idx}/{len(units)}: {unit_name}", flush=True)

                for stage in per_unit_stages:
                    # Generate stage key for completion tracking
                    # Single-unit: use simple name (code-generation)
                    # Multi-unit: use indexed name (code-generation-unit-2)
                    stage_key = stage if single_unit_mode else f"{stage}-unit-{unit_idx}"
                    stage_display = stage if single_unit_mode else f"{stage} (unit {unit_idx})"

                    if stage_key in completed:
                        _print_skip(stage_display)
                        continue

                    if stage in plan_skips:
                        skip_msg = f"{stage} (plan: SKIP)" if single_unit_mode else f"{stage} (unit {unit_idx}, plan: SKIP)"
                        _print_skip(skip_msg)
                        continue

                    _print_stage_start(stage_display)

                    # Fresh agent per stage — no accumulated conversation history.
                    construction_agent = build_construction_agent(
                        model_id=self.model_id,
                        mcp_tools=mcp_tools,
                        shared_state=self.shared_state,
                        hooks=hooks,
                        rules_base_path=self.rules_base_path,
                        max_output_tokens=self.max_output_tokens,
                    )

                    # For code-generation, add explicit instruction to write source files.
                    code_gen_hint = ""
                    if stage == "code-generation":
                        # Check project type from state
                        state_path = Path(abs_target_repo) / "aidlc-docs" / "aidlc-state.md"
                        is_brownfield = False
                        if state_path.exists():
                            state_content = state_path.read_text(encoding="utf-8")
                            is_brownfield = "brownfield" in state_content.lower()

                        if is_brownfield:
                            code_gen_hint = (
                                "\n\n🚨 MANDATORY BROWNFIELD CHECK (READ THIS FIRST):\n"
                                "1. Read ONLY 2 files: reverse-engineering/code-structure.md + api-documentation.md\n"
                                "2. Check if user story feature exists: endpoint + service method + tests\n"
                                "3. IF ALL EXIST: Write code-generation-skipped.md saying 'Feature complete, found [X, Y, Z]' → EXIT IMMEDIATELY\n"
                                "4. IF MISSING: Generate ONLY missing parts using write_source_file\n"
                                "⚠️ DO NOT create planning documents, DO NOT validate existing code, DO NOT use >50K tokens for check.\n"
                                "⚠️ Skipping this wastes $2-10. You MUST check existence BEFORE doing anything else."
                            )
                        else:
                            code_gen_hint = (
                                "\n\nGREENFIELD: Write source code files using write_source_file.\n"
                                "Generate main service/module and entry point for the feature."
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
                            f"UNIT OF WORK (focus on this unit):\n"
                            f"  Name: {unit_name}\n"
                            f"  Description: {unit_desc}\n"
                            f"  Unit {unit_idx} of {len(units)} total units\n\n"
                            f"INCEPTION PHASE CONTEXT:\n{inception_context}\n\n"
                            f"Execute ONLY this single stage for the unit '{unit_name}'. "
                            f"Write all planning artifacts using write_aidlc_artifact. "
                            f"Write source code using write_source_file. "
                            f"Call update_workflow_state when done. "
                            f"Do NOT call request_approval — the orchestrator handles approval."
                            f"{code_gen_hint}"
                        ),
                    )

                    # After code-generation, verify source files were actually written.
                    if stage == "code-generation":
                        from app.skills.stage_tracker import get_written
                        source_files = [f for t, f in get_written() if t == "source"]
                        artifacts = [f for t, f in get_written() if t == "artifact"]

                        # Check if agent explicitly skipped code generation (brownfield feature exists)
                        skip_marker_exists = any("code-generation-skipped" in f for f in artifacts)

                        if not source_files and not skip_marker_exists:
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
                                    f"Generate source code for unit '{unit_name}': {unit_desc}\n"
                                    f"User story: {user_story}\n"
                                    f"Target repository: {abs_target_repo}\n\n"
                                    f"INCEPTION CONTEXT:\n{inception_context}\n\n"
                                    f"You MUST write source files using write_source_file. "
                                    f"The existing source tree is shown in the inception context above — "
                                    f"use the EXACT same language, structure, and directory paths. "
                                    f"Do NOT introduce new packages or modules outside the existing structure.\n\n"
                                    f"At minimum, create the main service/module and any required entry points "
                                    f"for the unit '{unit_name}' described above.\n\n"
                                    f"Use write_source_file with target_repo='{abs_target_repo}' and "
                                    f"relative_path matching the existing source tree structure shown above.\n"
                                    f"Do NOT call update_workflow_state or request_approval."
                                ),
                            )
                        elif skip_marker_exists:
                            try:
                                from rich.console import Console
                                Console().print(
                                    "  [dim]✓  Feature already exists — skipped code generation (cost optimization)[/dim]"
                                )
                            except ImportError:
                                print("  ✓  Feature exists — skipped generation", flush=True)

                    approved = _request_approval_python(stage_display, str(stage_result), abs_target_repo, self.auto_approve)
                    if not approved:
                        self._logger.log({"type": "stage_rejected", "stage": stage_key,
                                          "timestamp": datetime.now(timezone.utc).isoformat()})
                        break

                    # Ensure stage is recorded as complete with unit-specific key.
                    completed_check = self._get_completed_stages(abs_target_repo)
                    if stage_key not in completed_check:
                        update_workflow_state(target_repo=abs_target_repo, stage_name=stage_key, status="complete")

            # Post-unit stage: build-and-test (runs once after all units)
            if post_unit_stage not in completed and post_unit_stage not in plan_skips:
                _print_stage_start(post_unit_stage)

                construction_agent = build_construction_agent(
                    model_id=self.model_id,
                    mcp_tools=mcp_tools,
                    shared_state=self.shared_state,
                    hooks=hooks,
                    rules_base_path=self.rules_base_path,
                    max_output_tokens=self.max_output_tokens,
                )

                stage_result = _run_stage_with_retry(
                    agent=construction_agent,
                    stage=post_unit_stage,
                    abs_target_repo=abs_target_repo,
                    user_story=user_story,
                    logger=self._logger,
                    is_construction=True,
                    custom_prompt=(
                        f"Execute the '{post_unit_stage}' stage for:\n"
                        f"Target repository: {abs_target_repo}\n"
                        f"User story: {user_story}\n\n"
                        f"ALL UNITS COMPLETE: {len(units)} unit(s) have been implemented.\n\n"
                        f"INCEPTION PHASE CONTEXT:\n{inception_context}\n\n"
                        f"Build and test the complete implementation for all units. "
                        f"Write all artifacts using write_aidlc_artifact. "
                        f"Call update_workflow_state when done. "
                        f"Do NOT call request_approval — the orchestrator handles approval."
                    ),
                )

                approved = _request_approval_python(post_unit_stage, str(stage_result), abs_target_repo, self.auto_approve)
                if approved:
                    completed_check = self._get_completed_stages(abs_target_repo)
                    if post_unit_stage not in completed_check:
                        update_workflow_state(target_repo=abs_target_repo, stage_name=post_unit_stage, status="complete")
                else:
                    self._logger.log({"type": "stage_rejected", "stage": post_unit_stage,
                                      "timestamp": datetime.now(timezone.utc).isoformat()})

            construction_duration_ms = (time.monotonic() - construction_start) * 1000
            self.shared_state["construction"]["status"] = "complete"
            self.shared_state["construction"]["duration_ms"] = round(construction_duration_ms, 2)
            self._checkpoint_state()

            # Token usage is accumulated by TokenCountingHook across all agent instances.
            total_input = self._token_hook.input_tokens
            total_output = self._token_hook.output_tokens
            cache_read = self._token_hook.cache_read_tokens
            cache_creation = self._token_hook.cache_creation_tokens
            self.shared_state["session_metrics"]["input_tokens"] = total_input
            self.shared_state["session_metrics"]["output_tokens"] = total_output
            self.shared_state["session_metrics"]["total_tokens"] = total_input + total_output
            self.shared_state["session_metrics"]["cache_read_tokens"] = cache_read
            self.shared_state["session_metrics"]["cache_creation_tokens"] = cache_creation

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
        Start the MCP filesystem server and return a Strands MCPClient instance.

        MCPClient is a ToolProvider — it can be passed directly in the Agent
        tools list. Strands handles tool registration internally.

        The server is scoped to the workspace root. Returns an empty list on
        failure so the workflow continues without MCP tools.

        Set ``AIDLC_DISABLE_MCP=1`` to skip MCP (agents use ``write_aidlc_artifact``,
        ``scan_directory``, and ``file_read`` only — same as AgentCore mode).
        """
        if os.environ.get("AIDLC_DISABLE_MCP", "").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            self._logger.log({
                "type": "info",
                "message": "MCP disabled via AIDLC_DISABLE_MCP; using direct file tools only",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return []

        try:
            from strands.tools.mcp import MCPClient
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            server_params = StdioServerParameters(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", str(_WORKSPACE_ROOT)],
            )

            mcp_client = MCPClient(lambda: stdio_client(server_params))
            # Keep a reference so the connection stays alive for the workflow.
            # Do NOT call start() here — the Strands SDK calls it via load_tools().
            self._mcp_client = mcp_client
            self._logger.log({
                "type": "info",
                "message": (
                    f"MCP filesystem server started (allowed dir: {_WORKSPACE_ROOT}). "
                    "If npx prints 'Client does not support MCP Roots', that is expected."
                ),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return [mcp_client]

        except Exception as exc:
            self._logger.log({
                "type": "warning",
                "message": f"MCP client unavailable — continuing without MCP tools: {exc}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
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
            metrics["cache_read_tokens"] = self._token_hook.cache_read_tokens
            metrics["cache_creation_tokens"] = self._token_hook.cache_creation_tokens
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
