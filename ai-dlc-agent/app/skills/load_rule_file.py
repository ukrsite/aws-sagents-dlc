"""Skill: load an AI-DLC stage rule file from the rule-details directory."""

from __future__ import annotations

import os
from pathlib import Path

from strands import tool

from app.errors import SkillOutputError
from app.retry import retry_with_backoff

# Resolve the rules base path relative to the workspace root (parent of ai-dlc-agent/).
# __file__ = .../ai-dlc-agent/app/skills/load_rule_file.py
# .parent       = .../ai-dlc-agent/app/skills/
# .parent.parent = .../ai-dlc-agent/app/
# .parent.parent.parent = .../ai-dlc-agent/
# .parent.parent.parent.parent = workspace root (aws-sagents-dlc/)
_WORKSPACE_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
RULES_BASE_PATH = _WORKSPACE_ROOT / ".kiro/aws-aidlc-rule-details"

# Core workflow file — loaded at agent startup.
CORE_WORKFLOW_PATH = _WORKSPACE_ROOT / ".kiro/steering/aws-aidlc-rules/core-workflow.md"

# Mapping from stage name to relative file path under RULES_BASE_PATH.
STAGE_FILE_MAP: dict[str, str] = {
    "core-workflow": str(CORE_WORKFLOW_PATH),  # absolute path — handled specially
    "workspace-detection": "inception/workspace-detection.md",
    "reverse-engineering": "inception/reverse-engineering.md",
    "requirements-analysis": "inception/requirements-analysis.md",
    "user-stories": "inception/user-stories.md",
    "workflow-planning": "inception/workflow-planning.md",
    "application-design": "inception/application-design.md",
    "units-generation": "inception/units-generation.md",
    "functional-design": "construction/functional-design.md",
    "nfr-requirements": "construction/nfr-requirements.md",
    "nfr-design": "construction/nfr-design.md",
    "infrastructure-design": "construction/infrastructure-design.md",
    "code-generation": "construction/code-generation.md",
    "build-and-test": "construction/build-and-test.md",
}

KNOWN_STAGES: list[str] = list(STAGE_FILE_MAP.keys())

MIN_CONTENT_LENGTH = 10


def _read_rule_file(stage_name: str) -> str:
    """
    Internal helper that reads the rule file for the given stage.
    """
    if stage_name not in STAGE_FILE_MAP:
        raise SkillOutputError(
            operation_name="load_rule_file",
            attempts=1,
            last_error=(
                f"Unknown stage name '{stage_name}'. "
                f"Valid stages: {sorted(STAGE_FILE_MAP.keys())}"
            ),
        )

    # core-workflow uses an absolute path stored directly in the map value.
    if stage_name == "core-workflow":
        rule_path = Path(STAGE_FILE_MAP[stage_name])
    else:
        rule_path = RULES_BASE_PATH / STAGE_FILE_MAP[stage_name]

    content = rule_path.read_text(encoding="utf-8")

    if len(content) < MIN_CONTENT_LENGTH:
        raise SkillOutputError(
            operation_name="load_rule_file",
            attempts=1,
            last_error=(
                f"Rule file for stage '{stage_name}' is too short "
                f"({len(content)} chars, minimum {MIN_CONTENT_LENGTH})."
            ),
        )

    return content


# Wrap with retry for transient I/O errors (OSError, PermissionError, etc.).
# SkillOutputError is NOT retried — it signals a permanent failure.
_read_rule_file_with_retry = retry_with_backoff(
    max_attempts=3,
    initial_delay=1.0,
    operation_name="load_rule_file",
)(_read_rule_file)


@tool
def load_rule_file(stage_name: str) -> str:
    """
    Load the AI-DLC rule file for the specified workflow stage.

    Reads the corresponding Markdown rule file from
    ``.kiro/aws-aidlc-rule-details/`` and returns its full text
    content. The content governs how the agent should execute that stage.

    Args:
        stage_name: The AI-DLC stage identifier. Must be one of:
            workspace-detection, reverse-engineering, requirements-analysis,
            user-stories, workflow-planning, application-design,
            units-generation, functional-design, nfr-requirements, nfr-design,
            infrastructure-design, code-generation, build-and-test.

    Returns:
        Full text content of the rule file (Markdown string, ≥10 characters).

    Raises:
        SkillOutputError: If the stage name is unknown or the file is too short.
    """
    return _read_rule_file_with_retry(stage_name)
