"""
Bedrock Batch API integration for AI-DLC workflow.

Provides 50% cost discount for non-interactive stages that can tolerate latency.
Applicable to all stages except requirements-analysis (interactive questions).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3


class BatchJobManager:
    """
    Manages Bedrock Batch API jobs for cost-optimized stage execution.

    The Batch API offers 50% pricing discount but requires:
    - Async execution (results available after job completes)
    - S3 bucket for input/output
    - Minimum 1 record per batch

    Not suitable for:
    - requirements-analysis (interactive questions)
    - Stages requiring immediate user approval
    """

    def __init__(
        self,
        s3_bucket: str,
        s3_prefix: str = "aidlc-batch",
        region_name: str | None = None,
    ):
        """
        Initialize batch job manager.

        Args:
            s3_bucket: S3 bucket for batch input/output files
            s3_prefix: S3 key prefix for batch files
            region_name: AWS region (defaults to AWS_REGION env var)
        """
        self.s3_bucket = s3_bucket
        self.s3_prefix = s3_prefix
        self.region_name = region_name or "us-east-1"

        self.bedrock = boto3.client("bedrock", region_name=self.region_name)
        self.s3 = boto3.client("s3", region_name=self.region_name)

    def create_batch_job(
        self,
        model_id: str,
        records: list[dict[str, Any]],
        job_name: str,
    ) -> str:
        """
        Create a Bedrock batch inference job.

        Args:
            model_id: Bedrock model ID
            records: List of inference records (each has messages, system, etc.)
            job_name: Name for the batch job

        Returns:
            Job ID (ARN)
        """
        # Upload input to S3
        input_key = f"{self.s3_prefix}/input/{job_name}.jsonl"
        input_data = "\n".join(json.dumps(r) for r in records)

        self.s3.put_object(
            Bucket=self.s3_bucket,
            Key=input_key,
            Body=input_data.encode("utf-8"),
        )

        input_s3_uri = f"s3://{self.s3_bucket}/{input_key}"
        output_s3_uri = f"s3://{self.s3_bucket}/{self.s3_prefix}/output/{job_name}/"

        # Create batch job
        response = self.bedrock.create_model_invocation_job(
            jobName=job_name,
            roleArn=self._get_batch_role_arn(),
            modelId=model_id,
            inputDataConfig={
                "s3InputDataConfig": {
                    "s3Uri": input_s3_uri,
                }
            },
            outputDataConfig={
                "s3OutputDataConfig": {
                    "s3Uri": output_s3_uri,
                }
            },
        )

        return response["jobArn"]

    def wait_for_job(self, job_arn: str, poll_interval: int = 30) -> dict[str, Any]:
        """
        Poll batch job until completion.

        Args:
            job_arn: Job ARN from create_batch_job
            poll_interval: Seconds between status checks

        Returns:
            Job metadata dict

        Raises:
            RuntimeError: If job fails
        """
        while True:
            response = self.bedrock.get_model_invocation_job(jobIdentifier=job_arn)
            status = response["status"]

            if status == "Completed":
                return response
            elif status in ("Failed", "Stopped"):
                raise RuntimeError(f"Batch job {job_arn} failed with status: {status}")
            elif status in ("InProgress", "Submitted"):
                time.sleep(poll_interval)
            else:
                raise RuntimeError(f"Unknown batch job status: {status}")

    def get_results(self, job_metadata: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Fetch batch job results from S3.

        Args:
            job_metadata: Job metadata from wait_for_job

        Returns:
            List of result records
        """
        output_uri = job_metadata["outputDataConfig"]["s3OutputDataConfig"]["s3Uri"]
        # Output is written to {output_uri}/{job_id}.jsonl.out
        job_id = job_metadata["jobArn"].split("/")[-1]
        output_key = output_uri.replace(f"s3://{self.s3_bucket}/", "") + f"{job_id}.jsonl.out"

        obj = self.s3.get_object(Bucket=self.s3_bucket, Key=output_key)
        content = obj["Body"].read().decode("utf-8")

        return [json.loads(line) for line in content.strip().split("\n")]

    def _get_batch_role_arn(self) -> str:
        """
        Get IAM role ARN for batch jobs.

        In production, this should be an environment variable.
        For now, construct from AWS account ID.
        """
        import os

        role_arn = os.environ.get("BEDROCK_BATCH_ROLE_ARN")
        if role_arn:
            return role_arn

        # Construct default role ARN (assumes role exists)
        sts = boto3.client("sts")
        account_id = sts.get_caller_identity()["Account"]
        return f"arn:aws:iam::{account_id}:role/BedrockBatchInferenceRole"


def is_batch_eligible(stage_name: str, auto_approve: bool) -> bool:
    """
    Determine if a stage is eligible for batch API execution.

    Args:
        stage_name: Stage name (e.g., "workspace-detection")
        auto_approve: Whether workflow is in auto-approve mode

    Returns:
        True if stage can use batch API
    """
    # Requirements-analysis asks interactive questions (not batch-eligible in CLI mode)
    if stage_name == "requirements-analysis" and not auto_approve:
        return False

    # All other stages are batch-eligible
    return True


def create_batch_record(
    stage_name: str,
    system_prompt: str | list[dict[str, Any]],
    user_message: str,
    max_tokens: int = 8192,
) -> dict[str, Any]:
    """
    Create a batch API request record for a stage.

    Args:
        stage_name: Stage name (for recordId)
        system_prompt: System prompt (string or list of SystemContentBlocks)
        user_message: User message content
        max_tokens: Maximum output tokens

    Returns:
        Batch record dict (JSONL format)
    """
    # Normalize system prompt
    if isinstance(system_prompt, str):
        system = [{"text": system_prompt}]
    else:
        system = system_prompt

    return {
        "recordId": stage_name,
        "modelInput": {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "system": system,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": user_message}],
                }
            ],
        },
    }
