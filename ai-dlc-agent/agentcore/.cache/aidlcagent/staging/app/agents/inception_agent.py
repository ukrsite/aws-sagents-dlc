"""Inception Agent — handles all AI-DLC Inception phase stages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from strands import Agent
from strands.models import BedrockModel


def build_inception_agent(
    model_id: str,
    mcp_tools: list,
    shared_state: dict[str, Any],
    hooks: list,
    rules_base_path: str = ".kiro/aws-aidlc-rule-details",
) -> Agent:
    """
    Build and return the Inception_Agent.

    The Inception_Agent handles all seven Inception phase stages:
    - Workspace Detection (always)
    - Reverse Engineering (brownfield only)
    - Requirements Analysis (always)
    - User Stories (conditional)
    - Workflow Planning (always)
    - Application Design (conditional)
    - Units Generation (conditional)

    It reads AI-DLC rule files via ``load_rule_file``, writes planning artifacts
    to ``{target_repo}/aidlc-docs/inception/`` via MCP filesystem tools, and
    updates workflow state via ``update_workflow_state`` after each stage.

    Args:
        model_id: Amazon Bedrock model identifier.
        mcp_tools: Tools registered from the MCP filesystem server.
        shared_state: Mutable shared state dict (includes ``target_repo``).
        hooks: List of HookProvider instances (ToolCallLoggingHook, TokenCountingHook).
        rules_base_path: Base path to AI-DLC rule detail files.

    Returns:
        Configured Strands Agent instance.
    """
    from app.skills.load_rule_file import load_rule_file
    from app.skills.update_workflow_state import update_workflow_state
    from app.skills.scan_directory import scan_directory
    from app.skills.request_approval import request_approval
    from app.skills.write_aidlc_artifact import write_aidlc_artifact
    from strands_tools import file_read

    system_prompt = _build_inception_system_prompt(rules_base_path, shared_state)
    model = BedrockModel(
        model_id=model_id,
        boto_client_config=__import__("botocore.config", fromlist=["Config"]).Config(
            read_timeout=300,
            connect_timeout=30,
            retries={"max_attempts": 3, "mode": "adaptive"},
        ),
    )

    return Agent(
        name="inception_agent",
        description="Handles all AI-DLC Inception phase stages: Workspace Detection, Reverse Engineering, Requirements Analysis, User Stories, Workflow Planning, Application Design, and Units Generation.",
        model=model,
        system_prompt=system_prompt,
        tools=[load_rule_file, update_workflow_state, scan_directory, request_approval, write_aidlc_artifact, file_read, *mcp_tools],
        hooks=hooks,
        callback_handler=None,  # suppress streaming LLM output to stdout
    )


def _build_inception_system_prompt(
    rules_base_path: str,
    shared_state: dict[str, Any],
) -> str:
    """Build the inception agent system prompt — load only common rules, not per-stage rules."""
    # Load only the common rules (process overview, terminology) — NOT the per-stage rules.
    # Per-stage rules are loaded on-demand via load_rule_file() during execution.
    rules_content = _load_rules(rules_base_path, "common")
    target_repo = shared_state.get("target_repo", "<target_repo>")
    user_story = shared_state.get("user_story", "<user_story>")

    steering = f"""
You are the Inception Agent in the AI-DLC (AI-Driven Development Life Cycle) workflow.

TARGET REPOSITORY (absolute path): {target_repo}
USER STORY: {user_story}

All planning artifacts MUST be written to: {target_repo}/aidlc-docs/inception/

## CRITICAL RULES — READ BEFORE DOING ANYTHING

1. **LOAD CORE WORKFLOW FIRST**: Call `load_rule_file(stage_name="core-workflow")` immediately
   before executing any stage. This file defines the mandatory workflow rules you MUST follow.
2. **DO NOT ask the user for the user story or project details.** They are already provided above.
3. **DO NOT scan the entire workspace root recursively.** Use scan_directory with recursive=False
   or recursive=True with max_depth=2 on specific subdirectories only.
4. **DO NOT use file_read with mode="find" or mode="list"** — those modes do not exist.
   Use scan_directory(path=...) to list directory contents.
5. **If load_rule_file fails**, proceed without the rule file using your built-in AI-DLC knowledge.
   Do NOT retry indefinitely or ask the user about missing rule files.
6. **Execute stages immediately.** Do not ask for permission to start — begin with
   workspace-detection right now.

## YOUR TOOLS

- `load_rule_file(stage_name)` — reads the detailed rules for a stage. If it fails, proceed anyway.
- `scan_directory(path, recursive=False)` — lists files/dirs at a path. Use this to explore the repo.
- `file_read(path)` — reads a single file's content.
- `write_aidlc_artifact(target_repo, relative_path, content)` — **writes a planning artifact directly
  to `{target_repo}/aidlc-docs/{{relative_path}}`**. Use this to save every artifact you produce.
  You do NOT need permission to call this — write artifacts immediately as you produce them.
  Example: `write_aidlc_artifact(target_repo="{target_repo}", relative_path="inception/reverse-engineering/architecture.md", content="...")`
- `update_workflow_state(target_repo, stage_name, status)` — updates aidlc-state.md and audit.md.
- `request_approval(stage_name, summary)` — **MANDATORY after each stage** — pauses execution and waits for the user to type "approve" before you continue. You MUST call this tool; do NOT just print text and assume approval.

## INCEPTION PHASE STAGES

Execute in order. Skip conditional ones if not applicable:
1. **workspace-detection** (ALWAYS) — scan {target_repo} with scan_directory; determine Greenfield/Brownfield
2. **reverse-engineering** (CONDITIONAL — Brownfield only) — read key source files to understand existing code
3. **requirements-analysis** (ALWAYS) — analyze the user story and produce requirements.md.
   When generating clarifying questions, write them to
   `inception/requirements/requirement-verification-questions.md`.
   **IMPORTANT**: Generate at most 5 high-level questions. The FIRST question MUST always be:
   "What is the target implementation complexity?" with options:
   A) PoC/MVP — simplest possible, minimal dependencies
   B) Standard — production-ready but straightforward
   C) Enterprise — full security, scalability, observability, compliance
   D) Other
   The remaining 4 questions should focus on the most critical unknowns for the specific
   user story (e.g. auth approach, data model, API style). Do NOT ask about logging,
   monitoring, edge cases, or future considerations.
   Each question MUST have 3-4 lettered options (A, B, C, D) so the user can answer
   with a single letter. Keep question titles short (3-5 words).
4. **user-stories** (CONDITIONAL) — create stories.md and personas.md if needed
5. **workflow-planning** (ALWAYS) — produce execution-plan.md
6. **application-design** (CONDITIONAL) — produce component design artifacts
7. **units-generation** (CONDITIONAL) — produce unit-of-work.md

## AFTER EACH STAGE

1. Write all artifacts using `write_aidlc_artifact` — do this immediately, no permission needed.
   The `relative_path` argument is relative to `{target_repo}/aidlc-docs/` — do NOT include
   `aidlc-docs/` in the path. Correct examples:
   - `inception/reverse-engineering/architecture.md`  ✅
   - `inception/requirements/requirements.md`  ✅
   - `inception/requirements/requirement-verification-questions.md`  ✅
   - `inception/plans/execution-plan.md`  ✅
   WRONG: `aidlc-docs/inception/requirements/requirements.md`  ❌ (do not include aidlc-docs/)
2. Call `update_workflow_state(target_repo="{target_repo}", stage_name="<stage>", status="complete")`
3. Call `request_approval(stage_name="<stage>", summary="<2-5 bullet summary of what was produced>")`
   — this PAUSES execution and waits for the user to type "approve"
   — if the user types anything other than "approve"/"yes"/"continue", treat it as feedback and revise
4. Only after `request_approval` returns "approve" (or similar), proceed to the next stage

## START NOW

Begin immediately with **workspace-detection**:
1. Call `load_rule_file(stage_name="core-workflow")` to load the mandatory workflow rules
2. Call `load_rule_file(stage_name="workspace-detection")` — if it fails, skip and continue
3. Call `scan_directory(path="{target_repo}", recursive=False)` to see what exists
4. Determine Greenfield vs Brownfield based on what you find
5. Write `{target_repo}/aidlc-docs/aidlc-state.md` with initial state
6. Present findings and wait for approval
"""
    return (rules_content + steering).strip()


def _load_rules(rules_base_path: str, phase: str) -> str:
    """Load all rule files for the given phase directory."""
    rules_dir = Path(rules_base_path) / phase
    if not rules_dir.exists():
        return ""

    content_parts = []
    for rule_file in sorted(rules_dir.glob("*.md")):
        try:
            content_parts.append(
                f"\n\n## Rule: {rule_file.stem}\n{rule_file.read_text(encoding='utf-8')}"
            )
        except OSError:
            pass

    return "".join(content_parts)
