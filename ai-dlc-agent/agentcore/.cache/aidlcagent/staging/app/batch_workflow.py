"""
Batch-enabled workflow orchestrator for cost optimization.

Uses Bedrock Batch API for eligible stages (50% discount).
Falls back to synchronous execution for interactive stages.
"""

from __future__ import annotations

import os
from typing import Any

from app.batch_api import BatchJobManager, create_batch_record, is_batch_eligible
from app.workflow import WorkflowOrchestrator


class BatchEnabledOrchestrator(WorkflowOrchestrator):
    """
    Workflow orchestrator with Batch API support.

    Extends WorkflowOrchestrator to use Batch API for eligible stages,
    providing 50% cost savings on input/output tokens.
    """

    def __init__(
        self,
        model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        output_dir: str = "outputs",
        rules_base_path: str | None = None,
        auto_approve: bool = False,
        enable_batch: bool = True,
        batch_s3_bucket: str | None = None,
    ):
        """
        Initialize batch-enabled orchestrator.

        Args:
            model_id: Bedrock model ID
            output_dir: Directory for output artifacts
            rules_base_path: Path to AI-DLC rule detail files
            auto_approve: Auto-approve mode (AgentCore)
            enable_batch: Use Batch API for eligible stages
            batch_s3_bucket: S3 bucket for batch jobs (required if enable_batch=True)
        """
        super().__init__(
            model_id=model_id,
            output_dir=output_dir,
            rules_base_path=rules_base_path,
            auto_approve=auto_approve,
        )

        self.enable_batch = enable_batch
        self.batch_manager: BatchJobManager | None = None

        if enable_batch:
            if not batch_s3_bucket:
                batch_s3_bucket = os.environ.get("AIDLC_BATCH_S3_BUCKET")
                if not batch_s3_bucket:
                    raise ValueError(
                        "Batch API requires batch_s3_bucket parameter or "
                        "AIDLC_BATCH_S3_BUCKET environment variable"
                    )

            self.batch_manager = BatchJobManager(
                s3_bucket=batch_s3_bucket,
                s3_prefix="aidlc-batch",
                region_name=os.environ.get("AWS_REGION", "us-east-1"),
            )

    def _should_use_batch(self, stage_name: str) -> bool:
        """Check if stage should use Batch API."""
        if not self.enable_batch or not self.batch_manager:
            return False

        return is_batch_eligible(stage_name, self.auto_approve)

    # Note: Full integration would require modifying _run_stage_with_retry
    # to detect batch-eligible stages and route them through BatchJobManager.
    # For now, this is a framework - actual integration deferred to avoid
    # disrupting the working synchronous workflow.
