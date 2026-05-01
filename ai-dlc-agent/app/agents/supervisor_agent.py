"""Supervisor Agent — top-level orchestrator using agents-as-tools pattern."""

from __future__ import annotations

from typing import Any

from strands import Agent
from strands.models import BedrockModel

# Ordered list of all AI-DLC stages for reference in the system prompt.
INCEPTION_STAGES = [
    "workspace-detection",
    "reverse-engineering",
    "requirements-analysis",
    "user-stories",
    "workflow-planning",
    "application-design",
    "units-generation",
]

CONSTRUCTION_STAGES = [
    "functional-design",
    "nfr-requirements",
    "nfr-design",
    "infrastructure-design",
    "code-generation",
    "build-and-test",
]


def build_supervisor_agent(
    model_id: str,
    inception_agent: Agent,
    construction_agent: Agent,
    shared_state: dict[str, Any],
    hooks: list,
) -> Agent:
    """
    Build and return the Supervisor_Agent.

    The Supervisor_Agent implements the Strands agents-as-tools pattern,
    registering ``inception_agent`` and ``construction_agent`` as callable tools.
    It orchestrates the full AI-DLC workflow from Workspace Detection through
    Build and Test, delegating each phase to the appropriate sub-agent.

    The supervisor:
    - Checks ``{target_repo}/aidlc-docs/aidlc-state.md`` on startup to determine
      whether to start fresh or resume from the last incomplete stage.
    - Presents a stage completion summary and waits for explicit user approval
      before invoking the next stage agent.
    - Delegates all Inception stages to ``inception_agent``.
    - Delegates all Construction stages to ``construction_agent``.
    - On unrecoverable error: logs the failure and returns a partial result with
      all artifacts produced so far.

    Args:
        model_id: Amazon Bedrock model identifier.
        inception_agent: Configured Inception_Agent instance.
        construction_agent: Configured Construction_Agent instance.
        shared_state: Mutable shared state dict (includes ``target_repo``,
            ``user_story``, and per-phase results).
        hooks: List of HookProvider instances (ToolCallLoggingHook, TokenCountingHook).

    Returns:
        Configured Strands Agent instance with sub-agents registered as tools.
    """
    target_repo = shared_state.get("target_repo", "<target_repo>")
    user_story = shared_state.get("user_story", "<user_story>")

    system_prompt = _build_supervisor_system_prompt(target_repo, user_story)
    model = BedrockModel(model_id=model_id)

    # Register sub-agents as tools using the Strands agents-as-tools pattern.
    # .as_tool() wraps each Agent as a callable tool with a unique name and description.
    return Agent(
        name="supervisor_agent",
        model=model,
        system_prompt=system_prompt,
        tools=[
            inception_agent.as_tool(
                name="inception_agent",
                description="Handles all AI-DLC Inception phase stages: Workspace Detection, Reverse Engineering, Requirements Analysis, User Stories, Workflow Planning, Application Design, and Units Generation.",
            ),
            construction_agent.as_tool(
                name="construction_agent",
                description="Handles all AI-DLC Construction phase stages: Functional Design, NFR Requirements, NFR Design, Infrastructure Design, Code Generation, and Build & Test.",
            ),
        ],
        hooks=hooks,
    )


def _build_supervisor_system_prompt(target_repo: str, user_story: str) -> str:
    """Build the supervisor system prompt with full AI-DLC workflow description."""
    inception_stages_str = "\n".join(
        f"  - {s}" for s in INCEPTION_STAGES
    )
    construction_stages_str = "\n".join(
        f"  - {s}" for s in CONSTRUCTION_STAGES
    )

    return f"""
You are the Supervisor Agent in the AI-DLC (AI-Driven Development Life Cycle) workflow.

You are the top-level orchestrator. You have two sub-agents available as tools:
- inception_agent: handles all Inception phase stages
- construction_agent: handles all Construction phase stages

TARGET REPOSITORY: {target_repo}
USER STORY: {user_story}

## AI-DLC WORKFLOW

The full workflow consists of two phases:

### INCEPTION PHASE (delegate to inception_agent)
{inception_stages_str}

### CONSTRUCTION PHASE (delegate to construction_agent)
{construction_stages_str}

## STEERING CONSTRAINTS

1. STATE RESUMPTION — ALWAYS check {target_repo}/aidlc-docs/aidlc-state.md before
   starting any stage. If the file exists and contains a ``last_completed_stage``,
   resume from the stage immediately following it. Do NOT restart from
   workspace-detection if stages have already been completed.

2. STAGE APPROVAL — After each stage completes, present a brief summary of what was
   produced and wait for explicit user approval before proceeding to the next stage.
   The user must type "approve", "continue", or "yes" to proceed. Any other response
   should be treated as a request for changes.

3. DELEGATION — Delegate ALL Inception stages to inception_agent. Delegate ALL
   Construction stages to construction_agent. Never execute stage logic yourself.

4. ERROR HANDLING — If a sub-agent raises an unrecoverable error:
   a. Log the failure with a UTC timestamp
   b. Return a partial result containing all artifacts produced so far
   c. Include an "error" key in the result describing the failure
   Never silently swallow errors.

5. CONTEXT PASSING — When delegating to construction_agent, always include the
   Inception phase artifacts in the context so the Construction Agent has full
   information about the project requirements, design, and units of work.

## WORKFLOW EXECUTION

1. Check {target_repo}/aidlc-docs/aidlc-state.md for resumption state
2. Determine the starting stage (first incomplete stage, or workspace-detection if fresh)
3. For each Inception stage (in order, skipping already-completed ones):
   a. Invoke inception_agent with the stage context and target_repo
   b. Present completion summary to user
   c. Wait for user approval
4. After all Inception stages complete, present Inception phase summary
5. Wait for user approval to begin Construction phase
6. For each Construction stage (in order, per unit of work):
   a. Invoke construction_agent with the stage context, target_repo, and Inception artifacts
   b. Present completion summary to user
   c. Wait for user approval
7. Present final workflow completion summary

## RESULT FORMAT

Return a consolidated result dictionary containing:
- target_repo: the target repository path
- user_story: the original user story
- inception: inception phase results (status, completed_stages, artifact_paths, duration_ms)
- construction: construction phase results (status, completed_stages, artifact_paths, source_files_written, duration_ms)
- session_metrics: total_tool_calls, total_retries, total_tokens, total_duration_ms, total_stages_completed
- error: (optional) error description if workflow failed
""".strip()
