#!/usr/bin/env python3
"""Report oversized Python and TypeScript source files without failing."""

from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_THRESHOLD = 800
SOURCE_SUFFIXES = {".py", ".ts", ".tsx"}
EXCLUDED_DIRS = {
    ".conda",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "data/runtime",
    "dist",
    "htmlcov",
    "node_modules",
    "outputs",
    "playwright-report",
    "reports",
    "test-results",
}


def main() -> int:
    """Print files over the configured line threshold and always exit cleanly."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_THRESHOLD,
        help=f"Line count threshold to report. Defaults to {DEFAULT_THRESHOLD}.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Project root to scan. Defaults to the current directory.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    large_files = find_large_files(root, args.threshold)

    print(f"Large-file warning: scanning Python/TypeScript files over {args.threshold} lines.")
    if not large_files:
        print("Large-file warning: no oversized source files found.")
        return 0

    print("Large-file warning: oversized source files found:")
    for line_count, path in large_files:
        print(f"  {line_count:5d} lines  {path}")
    return 0


def find_large_files(root: Path, threshold: int) -> list[tuple[int, str]]:
    """Return source files whose line count is above the warning threshold."""
    large_files: list[tuple[int, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not is_source_file(path):
            continue
        if is_excluded(path, root):
            continue
        line_count = count_lines(path)
        if line_count > threshold:
            large_files.append((line_count, path.relative_to(root).as_posix()))
    return sorted(large_files, reverse=True)


def is_source_file(path: Path) -> bool:
    """Return whether the path is a source file this report should scan."""
    if path.name.endswith(".d.ts"):
        return False
    return path.suffix in SOURCE_SUFFIXES


def is_excluded(path: Path, root: Path) -> bool:
    """Return whether the path lives under a directory excluded from reporting."""
    relative_parts = path.relative_to(root).parts
    for index in range(1, len(relative_parts)):
        candidate = "/".join(relative_parts[:index])
        if candidate in EXCLUDED_DIRS:
            return True
    return any(part in EXCLUDED_DIRS for part in relative_parts)


def count_lines(path: Path) -> int:
    """Count file lines using replacement decoding for robustness."""
    with path.open("r", encoding="utf-8", errors="replace") as file:
        return sum(1 for _line in file)


if __name__ == "__main__":
    raise SystemExit(main())
