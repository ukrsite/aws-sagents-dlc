"""Simple per-stage artifact tracker shared across skills."""

from __future__ import annotations

_written_files: list[tuple[str, str]] = []  # (type, path) — "artifact" or "source"


def reset() -> None:
    """Clear the tracker at the start of each stage."""
    _written_files.clear()


def record(file_type: str, path: str) -> None:
    """Record a file written during the current stage."""
    _written_files.append((file_type, path))


def get_written() -> list[tuple[str, str]]:
    """Return a copy of files written in the current stage."""
    return list(_written_files)
