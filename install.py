#!/usr/bin/env python3
"""Install either independent Coderails provider with a read-only dry-run mode."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.installer import claude, codex
from scripts.installer.files import confirm, materialize
from scripts.installer.modes import arm_scripts


def parser() -> argparse.ArgumentParser:
    """Describe provider-specific CLI options without side effects."""
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--provider", choices=("claude", "codex"), default="claude")
    result.add_argument("--dry-run", action="store_true")
    result.add_argument("--memory-target")
    group = result.add_mutually_exclusive_group()
    group.add_argument("--integrity-gate", action="store_const", const="yes", dest="integrity_gate")
    group.add_argument("--no-integrity-gate", action="store_const", const="no", dest="integrity_gate")
    return result


def main(arguments: list[str] | None = None) -> int:
    """Validate provider boundaries before any local installation writes."""
    try:
        options = parser().parse_args(arguments)
    except SystemExit as error:
        return 0 if error.code == 0 else 1
    root, home = Path(__file__).resolve().parent, Path.home()
    if options.provider == "codex" and (options.memory_target is not None or options.integrity_gate is not None):
        print("--memory-target and integrity-gate options are Claude-only", file=sys.stderr)
        return 1
    try:
        if options.provider == "codex":
            codex_home = Path(os.environ.get("CODEX_HOME", str(home / ".codex")))
            if not shutil.which("codex"):
                raise ValueError("Codex CLI is required")
            codex.preflight(root, codex_home, datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
            materialize(root, dry_run=options.dry_run)
            codex.install(root, codex_home, dry_run=options.dry_run)
            return 0
        missing = [name for name in ("gh", "git") if not shutil.which(name)]
        if missing:
            raise ValueError("PREFLIGHT FAILED — missing tools: " + ", ".join(missing))
        claude.preflight(home)
        integrity = options.integrity_gate
        if integrity is None and sys.stdout.isatty():
            integrity = "yes" if confirm("Show the owner-run integrity gate setup command? [y/N] ") else "no"
        if integrity == "yes":
            print("Optional gate setup (run this yourself in your terminal):")
            print(f"  python3 {shlex.quote(str(root / 'scripts/integrity-gate/setup.py'))}")
            print("Nothing privileged was run by this installer.")
        memory = (
            Path(options.memory_target)
            if options.memory_target
            else home / ".claude/projects" / str(Path.cwd()).replace("/", "-") / "memory"
        )
        materialize(root, dry_run=options.dry_run)
        arm_scripts(root, dry_run=options.dry_run)
        claude.install(root, home, memory, dry_run=options.dry_run)
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
