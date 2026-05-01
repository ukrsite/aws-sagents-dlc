"""Skill: write generated application source code to {target_repo}/src/."""

from __future__ import annotations

from pathlib import Path

from strands import tool


@tool
def write_source_file(target_repo: str, relative_path: str, content: str) -> str:
    """
    Write generated application code to ``{target_repo}/{relative_path}``.

    This skill is exclusively for generated application source code. It enforces
    two strict path constraints:

    1. The resolved target file MUST be inside ``{target_repo}/``.
    2. The resolved target file MUST NOT be inside ``{target_repo}/aidlc-docs/``.

    Planning artifacts must NEVER be written with this skill — use
    ``write_aidlc_artifact`` instead.

    Args:
        target_repo: Path to the target repository (e.g.,
            ``kiro-sandbox/services/java-api``).
        relative_path: Path relative to ``{target_repo}/`` for the source file
            (e.g., ``src/main/java/com/example/UserService.java``).
        content: Source code content to write to the file.

    Returns:
        Absolute path of the written file as a string.

    Raises:
        ValueError: If the resolved path is outside ``{target_repo}/`` or
            inside ``{target_repo}/aidlc-docs/``.
        OSError: If the file cannot be written (permission error, disk full, etc.).
    """
    abs_repo = Path(target_repo).resolve()
    aidlc_docs_root = abs_repo / "aidlc-docs"

    # Resolve the target path — this collapses any ".." components.
    target_path = (abs_repo / relative_path).resolve()

    # Constraint 1: target must be inside target_repo.
    try:
        target_path.relative_to(abs_repo)
    except ValueError:
        raise ValueError(
            f"Path constraint violation: '{relative_path}' resolves to "
            f"'{target_path}', which is outside '{abs_repo}'. "
            "write_source_file may only write inside {target_repo}/."
        )

    # Constraint 2: target must NOT be inside aidlc-docs/.
    try:
        target_path.relative_to(aidlc_docs_root)
        # If relative_to succeeds, the path IS inside aidlc-docs — that's a violation.
        raise ValueError(
            f"Path constraint violation: '{relative_path}' resolves to "
            f"'{target_path}', which is inside '{aidlc_docs_root}'. "
            "write_source_file must not write into aidlc-docs/. "
            "Use write_aidlc_artifact for planning artifacts."
        )
    except ValueError as exc:
        # relative_to raises ValueError when the path is NOT a subpath.
        # That's the expected case (path is outside aidlc-docs) — swallow it.
        # Only re-raise if it's our explicit constraint violation message.
        if "write_source_file must not write into aidlc-docs" in str(exc):
            raise

    # Create parent directories and write the file.
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")

    return str(target_path)
