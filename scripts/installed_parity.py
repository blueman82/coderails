#!/usr/bin/env python3
"""Check source/assets inventory parity for installed Claude and Codex coderails bundles.

Compared files must match source bytes. Excludes every .pyc file, every path
containing a __pycache__ component, and .DS_Store files. A passing check does not
authenticate retained bytecode or prove executed-code integrity.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.release_manifest import source_files  # noqa: E402

IGNORED_DIRS = {"__pycache__"}
IGNORED_NAMES = {".DS_Store"}
IGNORED_SUFFIXES = (".pyc",)
RUNTIME_PATHS = (
    "hooks",
    "skills",
    "scripts",
    "commands",
    "agents",
    "capabilities",
    "instructions",
    "policy",
    "routines",
    ".claude-plugin",
    "packages/graph-semantics",
    "packages/codex",
)
REQUIRED_FILES = {
    "claude": (".claude-plugin/plugin.json", "hooks/hooks.json"),
    "codex": (".codex-plugin/plugin.json", "hooks/hooks.json"),
}


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


def _git_paths(source: Path, *arguments: str) -> set[str]:
    """Read the source inventory from Git; strict checks never guess without it."""
    result = subprocess.run(
        ["git", "-C", str(source), arguments[0], "-z", *arguments[1:]], capture_output=True, check=False
    )
    if result.returncode:
        raise ValueError("Git source inventory is unavailable")
    return {os.fsdecode(path) for path in result.stdout.split(b"\0") if path}


def _tracked_source(source: Path) -> set[str]:
    """Return tracked files after rejecting hidden runtime files in the source worktree."""
    top = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
    )
    if top.returncode or Path(top.stdout.strip()).resolve() != source.resolve():
        raise ValueError("Git source root is unavailable or does not match --source-root")
    tracked = _git_paths(source, "ls-files", "--cached")
    for mode in (("--others", "--exclude-standard"), ("--others", "--ignored", "--exclude-standard")):
        for path in sorted(_git_paths(source, "ls-files", *mode, "--directory", "--", *RUNTIME_PATHS)):
            if not (
                IGNORED_DIRS & set(Path(path).parts)
                or Path(path).name in IGNORED_NAMES
                or path.endswith(IGNORED_SUFFIXES)
            ):
                raise ValueError(f"untracked runtime source: {path}")
    return tracked


def main(argv: list[str] | None = None) -> int:
    """Compare each requested bundle and return 0 (match), 1 (drift) or 2 (usage error)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--claude-installed", type=Path)
    parser.add_argument("--codex-installed", type=Path)
    parser.add_argument(
        "--require-both", action="store_true", help="Refuse a release check if either provider is absent"
    )
    args = parser.parse_args(argv)
    source: Path = args.source_root
    plans = (
        ("claude", args.claude_installed, default_claude, source),
        ("codex", args.codex_installed, default_codex, source / "packages/codex"),
    )
    try:
        tracked: set[str] = _tracked_source(source) if args.require_both else set()
        runtime = source_files(source) if args.require_both else {}
    except (OSError, ValueError) as error:
        print(f"installed_parity: {error}", file=sys.stderr)
        return 2
    differences: list[str] = []
    missing = False
    for bundle, given, locate, reference in plans:
        installed: Path | None = given if given is not None else locate()
        if installed is None:
            missing = True
            print(f"{bundle}: not installed" + ("" if args.require_both else ", skipped"))
            continue
        for directory in (installed, reference):
            if not directory.is_dir():
                print(f"installed_parity: {bundle}: not a directory: {directory}", file=sys.stderr)
                return 2
        if args.require_both:
            if installed.is_symlink():
                print(f"installed_parity: {bundle}: installed root is a symlink: {installed}", file=sys.stderr)
                return 2
            if installed.resolve().is_relative_to(source.resolve()):
                print(
                    f"installed_parity: {bundle}: installed path is inside the source checkout: {installed}",
                    file=sys.stderr,
                )
                return 2
            try:
                linked = next((path for path in installed.rglob("*") if path.is_symlink()), None)
            except OSError as error:
                print(f"installed_parity: {bundle}: cannot inspect installed tree: {error}", file=sys.stderr)
                return 2
            if linked is not None:
                print(f"installed_parity: {bundle}: installed tree contains a symlink: {linked}", file=sys.stderr)
                return 2
            prefix = "packages/codex/" if bundle == "codex" else ""
            expected = {path[len(prefix) :] for path in tracked if path.startswith(prefix)}
            for required in (*REQUIRED_FILES[bundle], *runtime[bundle]):
                if required not in expected or not (installed / required).is_file():
                    print(f"installed_parity: {bundle}: required installed file missing: {required}", file=sys.stderr)
                    return 2
            extra = next((path for path in installed_files(installed) if path.as_posix() not in expected), None)
            if extra is not None:
                print(f"installed_parity: {bundle}: installed file is not tracked source: {extra}", file=sys.stderr)
                return 2
        found = compare(bundle, installed, reference)
        differences.extend(found)
        print(f"{bundle}: {len(found)} difference(s) ({installed} vs {reference})")
    for line in differences:
        print(line)
    return 1 if differences or (args.require_both and missing) else 0


if __name__ == "__main__":
    raise SystemExit(main())
