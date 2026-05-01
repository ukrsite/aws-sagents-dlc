"""Skill: pause execution and request explicit human approval before continuing."""

from __future__ import annotations

import signal
import sys

from strands import tool

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich import print as rprint
    _RICH = True
except ImportError:
    _RICH = False

TIMEOUT_SECONDS = 300  # 5 minutes


@tool
def request_approval(stage_name: str, summary: str) -> str:
    """
    Pause workflow execution and request explicit human approval before continuing.

    Call this tool after completing each AI-DLC stage to present a summary to
    the user and wait for their approval before proceeding to the next stage.
    This is the ONLY way to pause for human input — do not just print text and
    assume the user approved.

    Args:
        stage_name: Name of the stage that just completed (e.g., "reverse-engineering").
        summary: Brief summary of what was produced in this stage (2-5 bullet points,
                 plain text or Markdown).

    Returns:
        The user's response string. If the response is "approve", "yes", or "continue"
        (case-insensitive), the workflow should proceed. Any other response means the
        user wants changes — include their feedback in the return value.
    """
    if _RICH:
        return _rich_prompt(stage_name, summary)
    else:
        return _plain_prompt(stage_name, summary)


def _rich_prompt(stage_name: str, summary: str) -> str:
    """Render a rich-formatted approval panel and prompt."""
    console = Console()

    # Print a blank line to separate from any preceding agent output.
    console.print()

    # Render the stage summary inside a styled panel.
    console.print(
        Panel(
            Markdown(summary),
            title=f"[bold green]✅  Stage complete: {stage_name}[/bold green]",
            border_style="green",
            padding=(1, 2),
        )
    )

    console.print(
        "\n[bold]Type [green]approve[/green] to continue, "
        "or describe changes needed:[/bold]"
    )

    response = _read_with_timeout(TIMEOUT_SECONDS)

    if response is None:
        console.print(
            f"\n[yellow]⏱  No response within {TIMEOUT_SECONDS}s — "
            "treating as approved.[/yellow]"
        )
        return "approve"

    normalized = response.strip().lower()
    if normalized in ("approve", "yes", "continue", "y", "ok"):
        console.print("[green]→ Approved. Continuing...[/green]\n")
    else:
        console.print(f"[yellow]→ Feedback received. Revising...[/yellow]\n")

    return response.strip()


def _plain_prompt(stage_name: str, summary: str) -> str:
    """Fallback plain-text prompt when rich is not available."""
    print(f"\n{'=' * 70}", flush=True)
    print(f"✅  Stage complete: {stage_name}", flush=True)
    print(f"{'-' * 70}", flush=True)
    print(summary, flush=True)
    print(f"{'=' * 70}", flush=True)
    print(
        '\nType "approve" to continue to the next stage, or describe changes needed:',
        flush=True,
    )

    response = _read_with_timeout(TIMEOUT_SECONDS)

    if response is None:
        print(f"\n⏱  No response within {TIMEOUT_SECONDS}s — treating as approved.", flush=True)
        return "approve"

    print(f"\n→ Response: {response}\n", flush=True)
    return response


def _read_with_timeout(timeout: int) -> str | None:
    """Read a line from stdin with a timeout. Returns None on timeout."""

    def _timeout_handler(signum: int, frame: object) -> None:
        raise TimeoutError()

    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout)
    try:
        return input()
    except TimeoutError:
        return None
    except EOFError:
        # Non-interactive stdin (e.g., piped input) — auto-approve.
        return "approve"
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
