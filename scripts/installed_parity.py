#!/usr/bin/env python3
"""Check that installed Claude and Codex coderails bundles are byte-identical to their source tree."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from pathlib import Path

IGNORED_DIRS = {"__pycache__"}
IGNORED_NAMES = {".DS_Store"}
IGNORED_SUFFIXES = (".pyc",)


def installed_files(root: Path) -> Iterator[Path]:
    """Yield regular files under root as relative paths, skipping ignored cache and Finder files."""
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if IGNORED_DIRS & set(relative.parts) or path.name in IGNORED_NAMES or path.name.endswith(IGNORED_SUFFIXES):
            continue
        if path.is_file() and not path.is_symlink():
            yield relative


def compare(bundle: str, installed: Path, source: Path) -> list[str]:
    """Return one difference line per installed file that is absent from or differs from source."""
    found: list[str] = []
    for relative in installed_files(installed):
        counterpart = source / relative
        if not counterpart.is_file():
            found.append(f"DIFF {bundle}: {relative} (extra: absent from source {source})")
        elif counterpart.read_bytes() != (installed / relative).read_bytes():
            found.append(f"DIFF {bundle}: {relative} (differs from source)")
    return found


def default_claude() -> Path | None:
    """Return the installPath Claude Code recorded for coderails, or None when not installed."""
    try:
        data = json.loads((Path.home() / ".claude/plugins/installed_plugins.json").read_text())
        path = Path(data["plugins"]["coderails@coderails"][0]["installPath"])
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None
    return path if path.is_dir() else None


def default_codex() -> Path | None:
    """Return the newest installed Codex plugin version directory, or None when not installed."""
    versions = Path.home() / ".codex/plugins/cache/coderails/coderails-codex"
    candidates = [path for path in versions.glob("*") if path.is_dir()]
    # ponytail: newest by mtime; read the Codex install record if several versions coexist
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def main(argv: list[str] | None = None) -> int:
    """Compare each requested bundle and return 0 (match), 1 (drift) or 2 (usage error)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--claude-installed", type=Path)
    parser.add_argument("--codex-installed", type=Path)
    args = parser.parse_args(argv)
    source: Path = args.source_root
    plans = (
        ("claude", args.claude_installed, default_claude, source),
        ("codex", args.codex_installed, default_codex, source / "packages/codex"),
    )
    differences: list[str] = []
    for bundle, given, locate, reference in plans:
        installed: Path | None = given if given is not None else locate()
        if installed is None:
            print(f"{bundle}: not installed, skipped")
            continue
        for directory in (installed, reference):
            if not directory.is_dir():
                print(f"installed_parity: {bundle}: not a directory: {directory}", file=sys.stderr)
                return 2
        found = compare(bundle, installed, reference)
        differences.extend(found)
        print(f"{bundle}: {len(found)} difference(s) ({installed} vs {reference})")
    for line in differences:
        print(line)
    return 1 if differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
