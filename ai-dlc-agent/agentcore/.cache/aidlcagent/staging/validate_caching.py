#!/usr/bin/env python3
"""
Validation test for prompt caching implementation.

Tests a multi-unit workflow and analyzes:
1. Cache hit rates
2. Cost reduction vs non-cached baseline
3. Token distribution (input/output/cache_read/cache_creation)
"""

import json
import sys
from pathlib import Path

from app.workflow import WorkflowOrchestrator


def analyze_results(result: dict) -> dict:
    """Analyze workflow results and calculate caching metrics."""
    metrics = result.get("session_metrics", {})

    total = metrics.get("total_tokens", 0)
    inp = metrics.get("input_tokens", 0)
    out = metrics.get("output_tokens", 0)
    cache_read = metrics.get("cache_read_tokens", 0)
    cache_creation = metrics.get("cache_creation_tokens", 0)

    # Calculate costs (Claude Haiku 4.5 pricing)
    input_cost = inp / 1_000_000 * 1.0
    output_cost = out / 1_000_000 * 5.0
    cache_read_cost = cache_read / 1_000_000 * 0.1
    cache_creation_cost = cache_creation / 1_000_000 * 1.25

    total_cost = input_cost + output_cost + cache_read_cost + cache_creation_cost

    # Calculate what cost would be WITHOUT caching (cache reads would be regular input)
    baseline_cost = (inp + cache_read) / 1_000_000 * 1.0 + out / 1_000_000 * 5.0

    # Cache efficiency
    cacheable_tokens = cache_read + cache_creation
    cache_hit_rate = (cache_read / cacheable_tokens * 100) if cacheable_tokens > 0 else 0

    # Savings from caching
    cache_savings_dollars = baseline_cost - total_cost
    cache_savings_pct = (cache_savings_dollars / baseline_cost * 100) if baseline_cost > 0 else 0

    return {
        "tokens": {
            "total": total,
            "input": inp,
            "output": out,
            "cache_read": cache_read,
            "cache_creation": cache_creation,
        },
        "costs": {
            "total_usd": round(total_cost, 4),
            "input_usd": round(input_cost, 4),
            "output_usd": round(output_cost, 4),
            "cache_read_usd": round(cache_read_cost, 4),
            "cache_creation_usd": round(cache_creation_cost, 4),
            "baseline_usd": round(baseline_cost, 4),
        },
        "cache_efficiency": {
            "hit_rate_pct": round(cache_hit_rate, 1),
            "savings_usd": round(cache_savings_dollars, 4),
            "savings_pct": round(cache_savings_pct, 1),
        },
        "duration_s": round(metrics.get("total_duration_ms", 0) / 1000, 1),
    }


def print_report(analysis: dict):
    """Print formatted analysis report."""
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    console = Console()

    console.print("\n" + "="*70)
    console.print("[bold cyan]Prompt Caching Validation Report[/bold cyan]")
    console.print("="*70 + "\n")

    # Token distribution
    tokens = analysis["tokens"]
    token_table = Table(title="Token Distribution", show_header=True)
    token_table.add_column("Category", style="cyan")
    token_table.add_column("Count", justify="right", style="yellow")
    token_table.add_column("% of Total", justify="right", style="dim")

    total = tokens["total"]
    for key, value in tokens.items():
        if key != "total":
            pct = (value / total * 100) if total > 0 else 0
            token_table.add_row(
                key.replace("_", " ").title(),
                f"{value:,}",
                f"{pct:.1f}%"
            )
    token_table.add_row("[bold]Total[/bold]", f"[bold]{total:,}[/bold]", "100.0%")

    console.print(token_table)
    console.print()

    # Cost breakdown
    costs = analysis["costs"]
    cost_table = Table(title="Cost Analysis", show_header=True)
    cost_table.add_column("Item", style="cyan")
    cost_table.add_column("Cost (USD)", justify="right", style="yellow")
    cost_table.add_column("% of Total", justify="right", style="dim")

    total_cost = costs["total_usd"]
    cost_table.add_row("Input tokens", f"${costs['input_usd']:.4f}",
                       f"{costs['input_usd']/total_cost*100:.1f}%" if total_cost > 0 else "0%")
    cost_table.add_row("Output tokens", f"${costs['output_usd']:.4f}",
                       f"{costs['output_usd']/total_cost*100:.1f}%" if total_cost > 0 else "0%")
    cost_table.add_row("Cache read (90% discount)", f"${costs['cache_read_usd']:.4f}",
                       f"{costs['cache_read_usd']/total_cost*100:.1f}%" if total_cost > 0 else "0%")
    cost_table.add_row("Cache creation (25% premium)", f"${costs['cache_creation_usd']:.4f}",
                       f"{costs['cache_creation_usd']/total_cost*100:.1f}%" if total_cost > 0 else "0%")
    cost_table.add_row("[bold]Total (with caching)[/bold]",
                       f"[bold green]${costs['total_usd']:.4f}[/bold green]", "100.0%")
    cost_table.add_row("[dim]Baseline (no caching)[/dim]",
                       f"[dim]${costs['baseline_usd']:.4f}[/dim]", "—")

    console.print(cost_table)
    console.print()

    # Cache efficiency
    eff = analysis["cache_efficiency"]
    console.print(Panel(
        f"[bold]Cache Hit Rate:[/bold]  [yellow]{eff['hit_rate_pct']:.1f}%[/yellow]\n"
        f"[bold]Cost Savings:[/bold]    [green]${eff['savings_usd']:.4f}[/green] "
        f"([green]{eff['savings_pct']:.1f}%[/green] reduction)\n"
        f"[bold]Duration:[/bold]        [cyan]{analysis['duration_s']:.1f}s[/cyan]",
        title="[bold green]✅ Caching Performance[/bold green]",
        border_style="green",
    ))

    # Verdict
    console.print("\n[bold]Verdict:[/bold]")
    if eff["hit_rate_pct"] >= 80:
        console.print("  ✅ [green]Cache hit rate is excellent (≥80%)[/green]")
    elif eff["hit_rate_pct"] >= 60:
        console.print("  ⚠️  [yellow]Cache hit rate is moderate (60-80%)[/yellow]")
    else:
        console.print("  ❌ [red]Cache hit rate is low (<60%)[/red]")

    if eff["savings_pct"] >= 15:
        console.print("  ✅ [green]Cost savings meet target (≥15%)[/green]")
    elif eff["savings_pct"] >= 10:
        console.print("  ⚠️  [yellow]Cost savings below target (10-15%)[/yellow]")
    else:
        console.print("  ❌ [red]Cost savings insufficient (<10%)[/red]")

    console.print("\n" + "="*70 + "\n")


def main():
    """Run validation test."""
    print("\n" + "="*70)
    print("Starting prompt caching validation test...")
    print("="*70 + "\n")

    # Test configuration
    test_repo = "../test-multi-unit"
    test_story = (
        "Implement user authentication, profile management, and notification services "
        "as separate units with proper error handling and logging"
    )

    print(f"Target repo: {test_repo}")
    print(f"User story: {test_story}")
    print(f"Model: Claude Haiku 4.5 (us.anthropic.claude-haiku-4-5-20251001-v1:0)")
    print("\n" + "-"*70 + "\n")

    # Initialize orchestrator
    orchestrator = WorkflowOrchestrator(
        model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        output_dir="outputs",
        rules_base_path=".kiro/aws-aidlc-rule-details",
        auto_approve=False,  # CLI mode for visibility
    )

    # Run workflow
    try:
        result = orchestrator.run(
            target_repo=test_repo,
            user_story=test_story,
        )

        # Check for errors
        if "error" in result:
            print(f"\n❌ Workflow failed: {result['error']}\n")
            return 1

        # Analyze results
        analysis = analyze_results(result)

        # Save detailed results
        output_file = Path("outputs/caching_validation.json")
        output_file.parent.mkdir(exist_ok=True)
        with open(output_file, "w") as f:
            json.dump({
                "result": result,
                "analysis": analysis,
            }, f, indent=2)

        print(f"\n✅ Detailed results saved to: {output_file}\n")

        # Print report
        print_report(analysis)

        return 0

    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user\n")
        return 1
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}\n")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
