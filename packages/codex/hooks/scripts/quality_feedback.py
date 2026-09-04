#!/usr/bin/env python3
"""PostToolUse quality feedback for apply-patch source changes."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import cast

SOURCE_SUFFIXES = {
    ".bash",
    ".cfg",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}
PATCH_PATH = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.*)$|^\*\*\* Move to: (.*)$", re.MULTILINE)


def payload_object(raw_payload: str) -> dict[str, object]:
    """Decode a hook payload, treating malformed input as an empty mapping."""
    try:
        decoded: object = json.loads(raw_payload)
    except json.JSONDecodeError:
        return {}
    return cast(dict[str, object], decoded) if isinstance(decoded, dict) else {}


def patch_paths(command: object) -> list[str]:
    """Extract the established Add, Update, Delete, and Move patch paths."""
    if not isinstance(command, str):
        return []
    return [next(value for value in match.groups() if value is not None) for match in PATCH_PATH.finditer(command)]


def repo_for(path: Path) -> Path | None:
    """Find the Git root containing a changed file, if one exists."""
    probe = path.parent
    while not probe.is_dir() and probe != probe.parent:
        probe = probe.parent
    result = subprocess.run(
        ["git", "-C", str(probe), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    return Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None


def main() -> int:
    """Emit bounded warn-only feedback for changed supported source files."""
    payload = payload_object(sys.stdin.read())
    raw_cwd = payload.get("cwd")
    cwd = Path(raw_cwd if isinstance(raw_cwd, str) and raw_cwd else os.getcwd())
    tool_input = payload.get("tool_input")
    command = cast(dict[str, object], tool_input).get("command") if isinstance(tool_input, dict) else None
    checker = Path(__file__).parent / "lib" / "quality_check.py"
    if not checker.is_file():
        return 0
    feedback: list[str] = []
    for raw_path in patch_paths(command):
        changed = Path(raw_path) if Path(raw_path).is_absolute() else cwd / raw_path
        if not changed.is_file() or changed.suffix not in SOURCE_SUFFIXES:
            continue
        repo = repo_for(changed)
        if repo is None:
            continue
        result = subprocess.run(
            [sys.executable, str(checker), "--root", str(repo), "--paths", str(changed)],
            text=True,
            capture_output=True,
            check=False,
        )
        output = result.stdout + result.stderr
        if "0 finding(s)" not in output:
            feedback.append(output)
    if not feedback:
        return 0
    context = "coderails quality feedback (warn-only):\n" + "\n".join(feedback)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": context[:3000]}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
