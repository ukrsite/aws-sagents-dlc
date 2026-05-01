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
    rules_base_path: str = "kiro-sandbox/.kiro/aws-aidlc-rule-details",
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
    from strands_tools import file_read

    system_prompt = _build_inception_system_prompt(rules_base_path, shared_state)
    model = BedrockModel(model_id=model_id)

    return Agent(
        name="inception_agent",
        description="Handles all AI-DLC Inception phase stages: Workspace Detection, Reverse Engineering, Requirements Analysis, User Stories, Workflow Planning, Application Design, and Units Generation.",
        model=model,
        system_prompt=system_prompt,
        tools=[load_rule_file, update_workflow_state, scan_directory, request_approval, file_read, *mcp_tools],
        hooks=hooks,
    )


def _build_inception_system_prompt(
    rules_base_path: str,
    shared_state: dict[str, Any],
) -> str:
    """Load inception rule files and build the full system prompt."""
    rules_content = _load_rules(rules_base_path, "inception")
    target_repo = shared_state.get("target_repo", "<target_repo>")
    user_story = shared_state.get("user_story", "<user_story>")

    steering = f"""
You are the Inception Agent in the AI-DLC (AI-Driven Development Life Cycle) workflow.

TARGET REPOSITORY (absolute path): {target_repo}
USER STORY: {user_story}

All planning artifacts MUST be written to: {target_repo}/aidlc-docs/inception/

## CRITICAL RULES — READ BEFORE DOING ANYTHING

1. **DO NOT ask the user for the user story or project details.** They are already provided above.
2. **DO NOT scan the entire workspace root recursively.** Use scan_directory with recursive=False
   or recursive=True with max_depth=2 on specific subdirectories only.
3. **DO NOT use file_read with mode="find" or mode="list"** — those modes do not exist.
   Use scan_directory(path=...) to list directory contents.
4. **If load_rule_file fails**, proceed without the rule file using your built-in AI-DLC knowledge.
   Do NOT retry indefinitely or ask the user about missing rule files.
5. **Execute stages immediately.** Do not ask for permission to start — begin with
   workspace-detection right now.

## YOUR TOOLS

- `load_rule_file(stage_name)` — reads the detailed rules for a stage. If it fails, proceed anyway.
- `scan_directory(path, recursive=False)` — lists files/dirs at a path. Use this to explore the repo.
- `file_read(path)` — reads a single file's content.
- `update_workflow_state(target_repo, stage_name, status)` — updates aidlc-state.md and audit.md.
- `request_approval(stage_name, summary)` — **MANDATORY after each stage** — pauses execution and waits for the user to type "approve" before you continue. You MUST call this tool; do NOT just print text and assume approval.

## INCEPTION PHASE STAGES

Execute in order. Skip conditional ones if not applicable:
1. **workspace-detection** (ALWAYS) — scan {target_repo} with scan_directory; determine Greenfield/Brownfield
2. **reverse-engineering** (CONDITIONAL — Brownfield only) — read key source files to understand existing code
3. **requirements-analysis** (ALWAYS) — analyze the user story and produce requirements.md
4. **user-stories** (CONDITIONAL) — create stories.md and personas.md if needed
5. **workflow-planning** (ALWAYS) — produce execution-plan.md
6. **application-design** (CONDITIONAL) — produce component design artifacts
7. **units-generation** (CONDITIONAL) — produce unit-of-work.md

## AFTER EACH STAGE

1. Call `update_workflow_state(target_repo="{target_repo}", stage_name="<stage>", status="complete")`
2. Write the artifact to `{target_repo}/aidlc-docs/inception/<stage>/` using write_aidlc_artifact or file_read
3. Call `request_approval(stage_name="<stage>", summary="<2-5 bullet summary of what was produced>")`
   — this PAUSES execution and waits for the user to type "approve"
   — if the user types anything other than "approve"/"yes"/"continue", treat it as feedback and revise
4. Only after `request_approval` returns "approve" (or similar), proceed to the next stage

## START NOW

Begin immediately with **workspace-detection**:
1. Call `load_rule_file(stage_name="workspace-detection")` — if it fails, skip and continue
2. Call `scan_directory(path="{target_repo}", recursive=False)` to see what exists
3. Determine Greenfield vs Brownfield based on what you find
4. Write `{target_repo}/aidlc-docs/aidlc-state.md` with initial state
5. Present findings and wait for approval
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
