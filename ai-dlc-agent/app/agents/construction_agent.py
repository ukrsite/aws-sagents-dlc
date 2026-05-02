"""Construction Agent and WriteInterruptHook for the AI-DLC Strands Agent."""

from __future__ import annotations

import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from strands import Agent
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry
from strands.models import BedrockModel


class WriteInterruptHook(HookProvider):
    """
    Intercepts MCP filesystem write_file calls and requests human approval.

    Fires before every ``write_file`` MCP tool call, regardless of whether the
    target is a planning artifact (inside ``aidlc-docs/``) or application source
    code (outside ``aidlc-docs/``). Displays the file type, path, and content
    preview, then waits up to 60 seconds for "approve" or "reject".

    Attributes:
        MCP_WRITE_TOOL: Name of the MCP filesystem write tool to intercept.
        TIMEOUT_SECONDS: Seconds to wait for user input before treating as rejected.
    """

    MCP_WRITE_TOOL = "write_file"
    TIMEOUT_SECONDS = 60

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Register the before-tool-call callback."""
        registry.add_callback(BeforeToolCallEvent, self._approve_write)

    def _approve_write(self, event: BeforeToolCallEvent) -> None:
        """
        Intercept write_file calls and request human approval.

        Determines whether the write target is an ARTIFACT (inside aidlc-docs/)
        or SOURCE CODE (outside aidlc-docs/). Displays the file type, path, and
        content preview, then waits up to 60 seconds for "approve" or "reject".
        """
        tool_name = event.tool_use.get("name", "")
        if tool_name != self.MCP_WRITE_TOOL:
            return

        content = event.tool_use.get("input", {}).get("content", "")
        path = event.tool_use.get("input", {}).get("path", "")

        # Determine file type based on path.
        file_type = "ARTIFACT" if "aidlc-docs" in path else "SOURCE CODE"

        print("\n" + "=" * 70)
        print(f"⚠️  INTERRUPT: Construction Agent wants to write a {file_type} file")
        print(f"   File type   : {file_type}")
        print(f"   Target path : {path}")
        print(f"   Content preview:")
        print(f"{content[:500]}")
        if len(content) > 500:
            print(f"   ... ({len(content) - 500} more characters)")
        print("=" * 70)
        print('Type "approve" to write the file, or "reject" to cancel:')

        response = self._read_with_timeout(self.TIMEOUT_SECONDS)

        if response == "approve":
            print(f"✅ Write approved — {file_type}: {path}")
        else:
            reason = "timeout" if response is None else f"rejected by user: {response}"
            print(f"❌ Write cancelled ({reason}) — {file_type}: {path}")
            raise InterruptedError(
                f"Write to '{path}' ({file_type}) was {reason} at "
                f"{datetime.now(timezone.utc).isoformat()}"
            )

    @staticmethod
    def _read_with_timeout(timeout: int) -> str | None:
        """
        Read a line from stdin with a timeout.

        Returns:
            The stripped, lowercased input string, or None on timeout.
        """
        def _timeout_handler(signum: int, frame: Any) -> None:
            raise TimeoutError("No response within timeout period")

        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(timeout)
        try:
            return input().strip().lower()
        except TimeoutError:
            return None
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)


def build_construction_agent(
    model_id: str,
    mcp_tools: list,
    shared_state: dict[str, Any],
    hooks: list,
    rules_base_path: str = "kiro-sandbox/.kiro/aws-aidlc-rule-details",
) -> Agent:
    """
    Build and return the Construction_Agent.

    The Construction_Agent handles all Construction phase stages:
    - Functional Design (conditional, per-unit)
    - NFR Requirements (conditional, per-unit)
    - NFR Design (conditional, per-unit)
    - Infrastructure Design (conditional, per-unit)
    - Code Generation (always, per-unit)
    - Build and Test (always)

    It reads AI-DLC rule files via ``load_rule_file``, writes planning artifacts
    to ``{target_repo}/aidlc-docs/construction/`` via ``write_aidlc_artifact``,
    writes generated source code to ``{target_repo}/src/`` via ``write_source_file``,
    and updates workflow state via ``update_workflow_state`` after each stage.

    A ``WriteInterruptHook`` is always appended to the hooks list to intercept
    every MCP ``write_file`` call and request human approval.

    Args:
        model_id: Amazon Bedrock model identifier.
        mcp_tools: Tools registered from the MCP filesystem server.
        shared_state: Mutable shared state dict (includes ``target_repo``).
        hooks: List of HookProvider instances (WriteInterruptHook appended here).
        rules_base_path: Base path to AI-DLC rule detail files.

    Returns:
        Configured Strands Agent instance.
    """
    from app.skills.load_rule_file import load_rule_file
    from app.skills.write_aidlc_artifact import write_aidlc_artifact
    from app.skills.write_source_file import write_source_file
    from app.skills.update_workflow_state import update_workflow_state
    from app.skills.scan_directory import scan_directory
    from app.skills.request_approval import request_approval
    from strands_tools import file_read

    write_interrupt_hook = WriteInterruptHook()
    all_hooks = list(hooks) + [write_interrupt_hook]

    system_prompt = _build_construction_system_prompt(rules_base_path, shared_state)
    model = BedrockModel(
        model_id=model_id,
        boto_client_config=__import__("botocore.config", fromlist=["Config"]).Config(
            read_timeout=300,
            connect_timeout=30,
            retries={"max_attempts": 3, "mode": "adaptive"},
        ),
    )

    return Agent(
        name="construction_agent",
        description="Handles all AI-DLC Construction phase stages: Functional Design, NFR Requirements, NFR Design, Infrastructure Design, Code Generation, and Build & Test.",
        model=model,
        system_prompt=system_prompt,
        tools=[
            load_rule_file,
            write_aidlc_artifact,
            write_source_file,
            update_workflow_state,
            scan_directory,
            request_approval,
            file_read,
            *mcp_tools,
        ],
        hooks=all_hooks,
        callback_handler=None,  # suppress streaming LLM output to stdout
    )


def _build_construction_system_prompt(
    rules_base_path: str,
    shared_state: dict[str, Any],
) -> str:
    """Build the construction agent system prompt — load only common rules, not per-stage rules."""
    # Load only the common rules — NOT the per-stage rules.
    # Per-stage rules are loaded on-demand via load_rule_file() during execution.
    rules_content = _load_rules(rules_base_path, "common")
    target_repo = shared_state.get("target_repo", "<target_repo>")

    steering = f"""
You are the Construction Agent in the AI-DLC (AI-Driven Development Life Cycle) workflow.

TARGET REPOSITORY: {target_repo}
Planning artifacts MUST be written to: {target_repo}/aidlc-docs/construction/
Application source code MUST be written to: {target_repo}/src/ (or existing source tree)

Your role is to execute all Construction phase stages for the given unit(s) of work.
You have access to the following tools:
- load_rule_file(stage_name): reads the detailed rules for a specific AI-DLC stage
- write_aidlc_artifact(target_repo, relative_path, content): writes planning docs to aidlc-docs/
- write_source_file(target_repo, relative_path, content): writes application code to source tree
- update_workflow_state(target_repo, stage_name, status): updates aidlc-state.md and audit.md
- scan_directory(path, recursive=False): lists files/dirs at a path (use instead of file_read for directory listing)
- request_approval(stage_name, summary): **MANDATORY after each stage** — pauses execution and waits for the user to type "approve". You MUST call this tool; do NOT just print text and assume approval.
- file_read: reads files from the filesystem (community tool)
- MCP filesystem tools: read/write files in the target repo

CONSTRUCTION PHASE STAGES (execute per unit of work):
1. functional-design (CONDITIONAL) — detailed business logic design
2. nfr-requirements (CONDITIONAL) — non-functional requirements and tech stack selection
3. nfr-design (CONDITIONAL) — NFR patterns and logical components
4. infrastructure-design (CONDITIONAL) — map to actual infrastructure services
5. code-generation (ALWAYS) — Part 1: Planning, Part 2: Generation
6. build-and-test (ALWAYS) — build instructions and test strategy

STEERING CONSTRAINTS:
1. Produce ONLY technology-agnostic design artifacts unless the user explicitly requests
   a specific technology stack. Do not prescribe specific frameworks or libraries unless asked.

2. Generated application code MUST be written to {target_repo}/src/ (or the existing source
   tree structure) using the write_source_file tool. NEVER write source code into aidlc-docs/.

3. Planning artifacts (design docs, execution plans, NFR docs, etc.) MUST be written to
   {target_repo}/aidlc-docs/construction/ using the write_aidlc_artifact tool.
   NEVER write planning artifacts to the source tree.

4. **DO NOT generate clarifying questions.** The requirements have already been gathered
   in the Inception phase. Proceed directly with design and implementation based on the
   existing requirements and reverse engineering artifacts. If something is unclear,
   make a reasonable assumption and document it in the artifact.

5. After completing each stage:
   a. Call update_workflow_state(target_repo="{target_repo}", stage_name="<stage>", status="complete")
   b. Call request_approval(stage_name="<stage>", summary="<2-5 bullet summary>")
      — this PAUSES execution and waits for the user to type "approve"
      — if the user types anything other than "approve"/"yes"/"continue", treat it as feedback and revise
   c. Only after request_approval returns "approve" (or similar), proceed to the next stage

5. For each stage, first call load_rule_file(stage_name="<stage>") to read the detailed
   rules, then follow those rules exactly.

6. For Code Generation:
   - Part 1 (Planning): create a detailed code generation plan in
     {target_repo}/aidlc-docs/construction/plans/{{unit-name}}-code-generation-plan.md
     using write_aidlc_artifact. Wait for user approval of the plan.
   - Part 2 (Generation): execute the approved plan step by step, writing each source
     file to the correct location in {target_repo}/src/ using write_source_file.

7. For Brownfield projects: check if target files exist before writing. Modify in-place
   rather than creating duplicate files (e.g., never create ClassName_modified.java).

8. If a request asks you to do something outside the Construction phase scope (e.g., deploy
   code, write production scripts, manage infrastructure), politely refuse and explain
   which constraint was triggered.

WORKFLOW EXECUTION:
- Load the unit definition from {target_repo}/aidlc-docs/inception/application-design/unit-of-work.md
- Load the execution plan from {target_repo}/aidlc-docs/inception/plans/execution-plan.md
- Execute only the stages marked EXECUTE in the execution plan
- For each stage, call load_rule_file first, then follow the rules
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
