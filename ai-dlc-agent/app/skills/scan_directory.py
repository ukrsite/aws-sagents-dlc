"""Skill: list files and directories in a target path (non-recursive by default)."""

from __future__ import annotations

import os
from pathlib import Path

from strands import tool


@tool
def scan_directory(path: str, recursive: bool = False, max_depth: int = 3) -> str:
    """
    List files and directories at the given path.

    Use this tool to explore a repository or directory structure. Prefer
    non-recursive scans (recursive=False) unless you specifically need a deep
    listing. Never scan the entire workspace root recursively — always scope
    to a specific subdirectory.

    Args:
        path: Absolute or relative path to the directory to scan.
        recursive: If True, list files recursively up to max_depth levels.
                   Defaults to False (top-level listing only).
        max_depth: Maximum recursion depth when recursive=True. Defaults to 3.
                   Ignored when recursive=False.

    Returns:
        A formatted string listing the directory contents, or an error message
        if the path does not exist or is not a directory.
    """
    target = Path(path)

    if not target.exists():
        return f"Path does not exist: {path}"

    if not target.is_dir():
        return f"Path is not a directory: {path}"

    lines: list[str] = [f"Directory: {target.resolve()}", ""]

    if not recursive:
        # Simple top-level listing.
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
        for entry in entries:
            prefix = "📁 " if entry.is_dir() else "📄 "
            lines.append(f"{prefix}{entry.name}")
    else:
        # Recursive listing up to max_depth.
        def _walk(current: Path, depth: int, indent: str) -> None:
            if depth > max_depth:
                lines.append(f"{indent}... (max depth {max_depth} reached)")
                return
            try:
                entries = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name))
            except PermissionError:
                lines.append(f"{indent}[permission denied]")
                return
            for entry in entries:
                # Skip hidden dirs and common noise.
                if entry.name.startswith(".") or entry.name in (
                    "__pycache__", "node_modules", ".git", "target", "build",
                    ".venv", "venv", ".idea", ".gradle",
                ):
                    continue
                prefix = "📁 " if entry.is_dir() else "📄 "
                lines.append(f"{indent}{prefix}{entry.name}")
                if entry.is_dir():
                    _walk(entry, depth + 1, indent + "  ")

        _walk(target, 1, "")

    return "\n".join(lines)
