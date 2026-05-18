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
        auto_approve: If True, automatically approve all writes without prompting.
    """

    MCP_WRITE_TOOL = "write_file"
    TIMEOUT_SECONDS = 60

    def __init__(self, auto_approve: bool = False):
        """Initialize the hook with auto-approve flag."""
        self.auto_approve = auto_approve

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Register the before-tool-call callback."""
        registry.add_callback(BeforeToolCallEvent, self._approve_write)

    def _approve_write(self, event: BeforeToolCallEvent) -> None:
        """
        Intercept write_file calls and request human approval.

        Determines whether the write target is an ARTIFACT (inside aidlc-docs/)
        or SOURCE CODE (outside aidlc-docs/). Displays the file type, path, and
        content preview, then waits up to 60 seconds for "approve" or "reject".

        In auto-approve mode, automatically approves all writes without prompting.
        """
        tool_name = event.tool_use.get("name", "")
        if tool_name != self.MCP_WRITE_TOOL:
            return

        content = event.tool_use.get("input", {}).get("content", "")
        path = event.tool_use.get("input", {}).get("path", "")

        # Determine file type based on path.
        file_type = "ARTIFACT" if "aidlc-docs" in path else "SOURCE CODE"

        # Auto-approve mode: silently approve all writes
        if self.auto_approve:
            print(f"  💻 source:   {Path(path).name}" if file_type == "SOURCE CODE" else f"  📄 artifact: {Path(path).relative_to(Path(path).parent.parent)}")
            return

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
    rules_base_path: str = ".kiro/aws-aidlc-rule-details",
    max_output_tokens: int = 8192,
    auto_approve: bool = False,
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
    every MCP ``write_file`` call and request human approval (unless auto_approve=True).

    Args:
        model_id: Amazon Bedrock model identifier.
        mcp_tools: Tools registered from the MCP filesystem server.
        shared_state: Mutable shared state dict (includes ``target_repo``).
        hooks: List of HookProvider instances (WriteInterruptHook appended here).
        rules_base_path: Base path to AI-DLC rule detail files.
        auto_approve: If True, WriteInterruptHook auto-approves all writes.

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
    from strands.agent.conversation_manager import SlidingWindowConversationManager

    write_interrupt_hook = WriteInterruptHook(auto_approve=auto_approve)
    all_hooks = list(hooks) + [write_interrupt_hook]

    system_prompt = _build_construction_system_prompt(rules_base_path, shared_state)

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
        conversation_manager=SlidingWindowConversationManager(window_size=30),
        hooks=all_hooks,
        callback_handler=None,  # suppress streaming LLM output to stdout
    )


def _build_construction_system_prompt(
    rules_base_path: str,
    shared_state: dict[str, Any],
) -> str:
    """Build the construction agent system prompt — no pre-loaded rule files to save tokens."""
    target_repo = shared_state.get("target_repo", "<target_repo>")

    return f"""You are the Construction Agent in the AI-DLC workflow.

TARGET REPOSITORY: {target_repo}
ARTIFACTS ROOT: {target_repo}/aidlc-docs/construction/
SOURCE CODE ROOT: {target_repo}/src/ (or existing source tree)

## TOOLS
- `load_rule_file(stage_name)` — load detailed rules for a stage (call once per stage)
- `write_aidlc_artifact(target_repo, relative_path, content)` — write planning docs to aidlc-docs/
- `write_source_file(target_repo, relative_path, content)` — write application code to source tree
- `update_workflow_state(target_repo, stage_name, status)` — update aidlc-state.md
- `scan_directory(path, recursive=False)` — list files/dirs
- `request_approval(stage_name, summary)` — MANDATORY after each stage; waits for user approval
- `file_read(path)` — read a file

## STAGES (per unit of work)
1. functional-design (CONDITIONAL) — detailed business logic design
2. nfr-requirements (CONDITIONAL) — non-functional requirements
3. nfr-design (CONDITIONAL) — NFR patterns and logical components
4. infrastructure-design (CONDITIONAL) — map to infrastructure services
5. code-generation (ALWAYS) — Part 1: plan, Part 2: generate
6. build-and-test (ALWAYS) — build and test instructions

## RULES
- Load stage rules with load_rule_file before executing each stage.
- Write source code to {target_repo}/src/ using write_source_file. NEVER write code into aidlc-docs/.
- Write planning artifacts to {target_repo}/aidlc-docs/construction/ using write_aidlc_artifact.
- For Java: scan src/main/java/ to find the base package and use it for all new classes.
- Do NOT generate clarifying questions — requirements are already gathered. Make reasonable assumptions.
- For Brownfield: modify existing files in-place; never create duplicate files (e.g., no ClassName_modified.java).
- After each stage: call update_workflow_state, then call request_approval and wait for approval.

## CRITICAL: BROWNFIELD COST OPTIMIZATION
- **If feature already exists and is complete**: Do NOT perform extensive validation. Write a concise summary and exit.
- **Extensive multi-step validation is EXTREMELY EXPENSIVE** (consumes 2M+ tokens). Only validate if code generation is actually needed.
- **Quick existence check**: Read 1-2 key files to determine if feature exists. If yes, write brief confirmation and stop.
- **Token budget**: Aim for <50K tokens per stage. Avoid reading large numbers of files unless generating new code.

## WORKFLOW
1. Load unit definition from {target_repo}/aidlc-docs/inception/application-design/unit-of-work.md
2. Load execution plan from {target_repo}/aidlc-docs/inception/plans/execution-plan.md
3. Execute only stages marked EXECUTE in the plan
4. For each stage: call load_rule_file first, then follow the rules""".strip()
