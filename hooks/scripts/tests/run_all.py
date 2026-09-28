#!/usr/bin/env python3
"""Discover Python hook suites with isolated Git environment and honest skip totals."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

GIT_ENVIRONMENT = {
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_REPLACE_REF_BASE",
    "GIT_PREFIX",
    "GIT_SHALLOW_FILE",
}


def isolated_environment() -> dict[str, str]:
    """Remove Git repository selectors and all indexed configuration overrides."""
    return {
        key: value
        for key, value in os.environ.items()
        if key not in GIT_ENVIRONMENT and not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))
    }


def discover(directory: Path) -> list[Path]:
    """Return supported Python test filenames exactly once in stable order."""
    return sorted(
        {
            path
            for pattern in ("*_test.py", "test_*.py", "*.test.py")
            for path in directory.glob(pattern)
            if path.is_file()
        }
    )


def run_suites(directory: Path) -> int:
    """Run all discovered suites, separating prerequisite skips from genuine success."""
    retired = list(directory.glob("*.test.sh"))
    if retired:
        print("run_all: ERROR — shell test retirement is incomplete; refusing partial coverage", file=sys.stderr)
        return 1
    suites = discover(directory)
    if not suites:
        print(f"run_all: ERROR — no Python test files found in {directory}", file=sys.stderr)
        return 1
    failed = 0
    skipped = 0
    for suite in suites:
        print(f"\n=== {suite.name} ===", flush=True)
        code = subprocess.run(
            [sys.executable, str(suite)], cwd=directory, env=isolated_environment(), check=False
        ).returncode
        if code == 0:
            print("OK")
        elif code == 3:
            skipped += 1
            print(f"SKIPPED (prerequisite): {suite.name}")
        else:
            failed += 1
            print(f"FAILED (exit {code})")
    print(f"\n--- run_all: {len(suites) - failed - skipped}/{len(suites)} suites passed, {skipped} skipped ---")
    if skipped == len(suites):
        print(f"WARNING: all {len(suites)} suites skipped — nothing was actually verified", file=sys.stderr)
        return 1
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(run_suites(Path(__file__).resolve().parent))
