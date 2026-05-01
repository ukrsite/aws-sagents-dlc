"""CloudWatch metrics publisher for the AI-DLC Strands Agent."""

from __future__ import annotations

import logging
from typing import Any

import boto3
import botocore.exceptions

logger = logging.getLogger(__name__)


class CloudWatchMetrics:
    """
    Publishes session-level metrics to Amazon CloudWatch.

    Metrics are published under the namespace ``AI-DLC/StrandsAgent``.
    When not running on AWS (or when credentials are unavailable), the
    ``publish_session_metrics`` method no-ops gracefully.

    Args:
        region: AWS region name (e.g., "us-east-1").
    """

    NAMESPACE = "AI-DLC/StrandsAgent"

    def __init__(self, region: str) -> None:
        self._region = region
        self._client = boto3.client("cloudwatch", region_name=region)

    def publish_session_metrics(self, metrics: dict[str, Any]) -> None:
        """
        Publish session-level metrics to CloudWatch.

        Expected keys in ``metrics``:
            - total_tool_calls (int)
            - total_retries (int)
            - total_tokens (int)
            - total_duration_ms (float)

        Args:
            metrics: Dictionary of metric names to numeric values.
        """
        metric_data = [
            {
                "MetricName": "TotalToolCalls",
                "Value": float(metrics.get("total_tool_calls", 0)),
                "Unit": "Count",
            },
            {
                "MetricName": "TotalRetries",
                "Value": float(metrics.get("total_retries", 0)),
                "Unit": "Count",
            },
            {
                "MetricName": "TotalTokens",
                "Value": float(metrics.get("total_tokens", 0)),
                "Unit": "Count",
            },
            {
                "MetricName": "TotalDurationMs",
                "Value": float(metrics.get("total_duration_ms", 0)),
                "Unit": "Milliseconds",
            },
        ]

        try:
            self._client.put_metric_data(
                Namespace=self.NAMESPACE,
                MetricData=metric_data,
            )
            logger.info(
                "Published session metrics to CloudWatch namespace '%s'", self.NAMESPACE
            )
        except botocore.exceptions.ClientError as exc:
            logger.warning(
                "Could not publish metrics to CloudWatch (not running on AWS or "
                "insufficient permissions): %s",
                exc,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Unexpected error publishing CloudWatch metrics: %s", exc)
