"""SupervisorOrchestrator: top-level workflow entry point for the AI-DLC agent."""

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
from app.agents.supervisor_agent import build_supervisor_agent
from app.hooks.logging_hook import ToolCallLoggingHook
from app.hooks.token_hook import TokenCountingHook
from app.observability.logger import StructuredLogger
from app.observability.metrics import CloudWatchMetrics

DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
# Resolve rules path relative to the workspace root (parent of ai-dlc-agent/).
# __file__ = .../ai-dlc-agent/app/workflow.py
# .parent       = .../ai-dlc-agent/app/
# .parent.parent = .../ai-dlc-agent/
# .parent.parent.parent = workspace root (aws-sagents-dlc/)
_WORKSPACE_ROOT = Path(__file__).parent.parent.parent.resolve()
RULES_BASE_PATH = str(_WORKSPACE_ROOT / "kiro-sandbox/.kiro/aws-aidlc-rule-details")


class SupervisorOrchestrator:
    """
    Top-level orchestrator for the AI-DLC Strands Agent.

    Accepts a target repository path and a user story, then executes the full
    AI-DLC workflow (Inception → Construction) using a three-agent Supervisor
    pattern. All planning artifacts are written to ``{target_repo}/aidlc-docs/``
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
        3. Builds Inception_Agent, Construction_Agent, and Supervisor_Agent.
        4. Invokes the Supervisor_Agent with the target repo and user story.
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
            agent_name="supervisor_agent", logger=self._logger
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

            # Build supervisor with sub-agents as tools.
            supervisor_agent = build_supervisor_agent(
                model_id=self.model_id,
                inception_agent=inception_agent,
                construction_agent=construction_agent,
                shared_state=self.shared_state,
                hooks=hooks,
            )

            # Invoke the supervisor.
            supervisor_start = time.monotonic()
            supervisor_prompt = (
                f"Execute the full AI-DLC workflow for the following:\n\n"
                f"Target repository: {target_repo}\n"
                f"User story: {user_story}\n\n"
                f"Start by checking {target_repo}/aidlc-docs/aidlc-state.md for any "
                f"previous session state, then proceed with the workflow."
            )

            supervisor_result = supervisor_agent(supervisor_prompt)
            supervisor_duration_ms = (time.monotonic() - supervisor_start) * 1000

            supervisor_output = str(supervisor_result)
            self._logger.log_agent_invocation(
                agent_name="supervisor_agent",
                input_len=len(supervisor_prompt),
                output_len=len(supervisor_output),
                duration_ms=supervisor_duration_ms,
            )

            # Update shared state with supervisor output.
            self.shared_state["inception"]["status"] = "complete"
            self.shared_state["construction"]["status"] = "complete"

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
        self.shared_state["session_metrics"]["total_tokens"] = self._token_hook.total_tokens
        self.shared_state["session_metrics"]["total_duration_ms"] = round(total_duration_ms, 2)

        result: dict[str, Any] = {
            "target_repo": self.shared_state.get("target_repo", ""),
            "user_story": self.shared_state.get("user_story", ""),
            "inception": self.shared_state.get("inception", {}),
            "construction": self.shared_state.get("construction", {}),
            "session_metrics": self.shared_state["session_metrics"],
        }
        if error:
            result["error"] = error
        return result
