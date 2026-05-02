"""Skill: write an AI-DLC planning artifact to {target_repo}/aidlc-docs/."""

from __future__ import annotations

from pathlib import Path

from strands import tool


@tool
def write_aidlc_artifact(target_repo: str, relative_path: str, content: str) -> str:
    """
    Write a planning artifact to ``{target_repo}/aidlc-docs/{relative_path}``.

    This skill is exclusively for AI-DLC planning documents (requirements,
    design docs, execution plans, etc.). It enforces a strict path constraint:
    the resolved target file MUST be inside ``{target_repo}/aidlc-docs/``.
    Application source code must NEVER be written with this skill — use
    ``write_source_file`` instead.

    Args:
        target_repo: Path to the target repository (e.g.,
            ``kiro-sandbox/services/java-api``).
        relative_path: Path relative to ``{target_repo}/aidlc-docs/``
            (e.g., ``inception/requirements/requirements.md``).
        content: Text content to write to the file.

    Returns:
        Absolute path of the written file as a string.

    Raises:
        ValueError: If the resolved path is outside ``{target_repo}/aidlc-docs/``
            (including path traversal attempts like ``../../src/Foo.java``).
        OSError: If the file cannot be written (permission error, disk full, etc.).
    """
    abs_repo = Path(target_repo).resolve()
    aidlc_docs_root = abs_repo / "aidlc-docs"

    # Resolve the target path — this collapses any ".." components.
    target_path = (aidlc_docs_root / relative_path).resolve()

    # Enforce the path constraint: target must be inside aidlc-docs/.
    try:
        target_path.relative_to(aidlc_docs_root)
    except ValueError:
        raise ValueError(
            f"Path constraint violation: '{relative_path}' resolves to "
            f"'{target_path}', which is outside '{aidlc_docs_root}'. "
            "write_aidlc_artifact may only write inside {target_repo}/aidlc-docs/."
        )

    # Create parent directories and write the file.
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")

    # Print progress line — filename only, no content.
    try:
        from rich.console import Console
        Console().print(f"  [dim]📄 artifact:[/dim] [cyan]{relative_path}[/cyan]")
    except ImportError:
        print(f"  📄 artifact: {relative_path}", flush=True)

    return str(target_path)
