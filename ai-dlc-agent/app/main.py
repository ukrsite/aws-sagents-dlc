"""CLI entry point for the AI-DLC Strands Agent."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from dotenv import load_dotenv

# Load .env from the ai-dlc-agent/ directory (where this package lives).
# Variables already set in the environment take precedence (override=False).
load_dotenv()

import logging

# Suppress verbose Strands SDK tool-call output unless AIDLC_VERBOSE=1 is set.
# The SDK logs "Tool #N: ..." at INFO level via the "strands" logger.
_verbose = os.environ.get("AIDLC_VERBOSE", "").lower() in ("1", "true", "yes")
logging.basicConfig(
    level=logging.DEBUG if _verbose else logging.WARNING,
    format="%(message)s",
)
# Always keep our own app logger at WARNING to avoid noise from boto3/botocore.
for _noisy in ("boto3", "botocore", "urllib3", "s3transfer"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

from app.errors import ConfigurationError
from app.workflow import DEFAULT_MODEL_ID, SupervisorOrchestrator


def validate_env() -> None:
    """
    Validate that required AWS environment variables are present.

    Raises:
        ConfigurationError: If AWS_REGION is missing.
    """
    missing: list[str] = []

    if not os.environ.get("AWS_REGION"):
        missing.append("AWS_REGION")

    # boto3 will pick up credentials from IAM role / instance profile automatically.
    # We only require AWS_REGION to be explicitly set.
    if missing:
        raise ConfigurationError(missing)


def main() -> None:
    """CLI entry point for the AI-DLC Strands Agent."""
    parser = argparse.ArgumentParser(
        prog="ai-dlc-agent",
        description=(
            "AI-DLC Strands Agent — analyzes a target repository and implements "
            "a user story by walking through the full AI-DLC Software Development Cycle."
        ),
    )
    parser.add_argument(
        "--repo",
        "-r",
        required=True,
        help=(
            "Path to the target repository to analyze and modify "
            "(e.g., 'kiro-sandbox/services/java-api')"
        ),
    )
    parser.add_argument(
        "--story",
        "-s",
        required=True,
        help=(
            "User story to implement "
            "(e.g., \"As a user, I want to reset my password\")"
        ),
    )
    parser.add_argument(
        "--model-id",
        "-m",
        default=DEFAULT_MODEL_ID,
        help=f"Bedrock model ID (default: {DEFAULT_MODEL_ID})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate environment and print config without invoking agents",
    )

    args = parser.parse_args()

    try:
        validate_env()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print("✅ Environment validated successfully.")
        print(f"   Model ID    : {args.model_id}")
        print(f"   Target repo : {args.repo}")
        story_preview = args.story[:100] + ("..." if len(args.story) > 100 else "")
        print(f"   User story  : {story_preview}")
        sys.exit(0)

    orchestrator = SupervisorOrchestrator(model_id=args.model_id)

    try:
        result = orchestrator.run(
            target_repo=args.repo,
            user_story=args.story,
        )
    except Exception as exc:
        print(f"Fatal error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Print the final result summary using rich if available.
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich import print as rprint
        console = Console()
        console.print()
        if "error" in result:
            console.print(
                Panel(
                    f"[red]{result['error']}[/red]",
                    title="[bold red]Workflow failed[/bold red]",
                    border_style="red",
                )
            )
        else:
            console.print(
                Panel(
                    "[green]Workflow completed successfully.[/green]\n"
                    f"Target repo: [bold]{result.get('target_repo', '')}[/bold]\n"
                    f"Tokens used: [bold]{result.get('session_metrics', {}).get('total_tokens', 0)}[/bold]\n"
                    f"Duration: [bold]{result.get('session_metrics', {}).get('total_duration_ms', 0):.0f}ms[/bold]",
                    title="[bold green]✅  AI-DLC Workflow Complete[/bold green]",
                    border_style="green",
                )
            )
    except ImportError:
        import json as _json
        print(_json.dumps(result, indent=2, default=str))

    if "error" in result:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
