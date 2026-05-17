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
    max_output_tokens: int = 8192,
    auto_approve: bool = False,
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
        auto_approve: If True (AgentCore), auto-fill questions. If False (CLI), blank for user input.

    Returns:
        Configured Strands Agent instance.
    """
    from app.skills.load_rule_file import load_rule_file
    from app.skills.update_workflow_state import update_workflow_state
    from app.skills.scan_directory import scan_directory
    from app.skills.request_approval import request_approval
    from app.skills.write_aidlc_artifact import write_aidlc_artifact
    from strands_tools import file_read
    from strands.agent.conversation_manager import SlidingWindowConversationManager

    system_prompt = _build_inception_system_prompt(rules_base_path, shared_state, auto_approve)

    model = BedrockModel(
        model_id=model_id,
        max_tokens=max_output_tokens,
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
        conversation_manager=SlidingWindowConversationManager(window_size=30),
        hooks=hooks,
        callback_handler=None,  # suppress streaming LLM output to stdout
    )


def _build_inception_system_prompt(
    rules_base_path: str,
    shared_state: dict[str, Any],
    auto_approve: bool = False,
) -> str:
    """Build the inception agent system prompt — no pre-loaded rule files to save tokens."""
    target_repo = shared_state.get("target_repo", "<target_repo>")
    user_story = shared_state.get("user_story", "<user_story>")

    question_generation_mode = (
        "**AUTO-APPROVE MODE (AgentCore/Serverless)**\n"
        "   Generate questions WITH reasonable default answers pre-filled.\n"
        "   Choose the most standard/common option (typically B for complexity, exact match for identifiers).\n"
        "   Format each answer as: [Answer]: B) Option text"
    ) if auto_approve else (
        "**INTERACTIVE MODE (CLI)**\n"
        "   Generate questions WITH [Answer]: tag but leave the answer BLANK.\n"
        "   Format: [Answer]: (empty line after colon)\n"
        "   Users will fill in answers interactively."
    )

    return f"""You are the Inception Agent in the AI-DLC workflow.

TARGET REPOSITORY: {target_repo}
USER STORY: {user_story}
ARTIFACTS ROOT: {target_repo}/aidlc-docs/inception/

## RULES
- DO NOT ask the user for project details — they are provided above.
- DO NOT scan the workspace root recursively. Use scan_directory with recursive=False or max_depth=2.
- DO NOT use file_read with mode="find" or mode="list" — use scan_directory instead.
- If load_rule_file fails, proceed using built-in AI-DLC knowledge. Do NOT retry or ask the user.
- Execute stages immediately without asking permission.

## TOOLS
- `load_rule_file(stage_name)` — load detailed rules for a stage (call once per stage, not at startup)
- `scan_directory(path, recursive=False)` — list files/dirs
- `file_read(path)` — read a file
- `write_aidlc_artifact(target_repo, relative_path, content)` — write artifact to {target_repo}/aidlc-docs/{{relative_path}}. relative_path must NOT include "aidlc-docs/".
- `update_workflow_state(target_repo, stage_name, status)` — update aidlc-state.md
- `request_approval(stage_name, summary)` — MANDATORY after each stage; waits for user approval

## STAGES (execute in order, skip conditional ones if not applicable)
1. workspace-detection (ALWAYS) — scan {target_repo}; determine Greenfield/Brownfield
2. reverse-engineering (CONDITIONAL — Brownfield only) — read key source files
3. requirements-analysis (ALWAYS) — produce requirements.md + requirement-verification-questions.md
   - Max 5 questions. First question MUST be implementation complexity (A=PoC, B=Standard, C=Enterprise, D=Other).
   - Each question needs 3-4 lettered options. No questions about logging/monitoring/edge cases.
   - CRITICAL: {question_generation_mode}
4. user-stories (CONDITIONAL) — create stories.md and personas.md
5. workflow-planning (ALWAYS) — produce execution-plan.md
6. application-design (CONDITIONAL) — produce component design artifacts
7. units-generation (CONDITIONAL) — produce unit-of-work.md

## AFTER EACH STAGE
1. Write artifacts with write_aidlc_artifact immediately (no permission needed)
2. Call update_workflow_state(target_repo="{target_repo}", stage_name="<stage>", status="complete")
3. Call request_approval(stage_name="<stage>", summary="<2-5 bullet summary>")
4. Only proceed to next stage after request_approval returns approval

## START NOW — workspace-detection
1. Call load_rule_file(stage_name="workspace-detection") — if it fails, skip and continue
2. Call scan_directory(path="{target_repo}", recursive=False)
3. Determine Greenfield vs Brownfield
4. Call update_workflow_state(target_repo="{target_repo}", stage_name="workspace-detection", status="complete")
5. Call request_approval to present findings""".strip()
