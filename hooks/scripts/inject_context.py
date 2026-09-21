#!/usr/bin/env python3
"""UserPromptSubmit hook: inject current date, cwd, and git branch into context.

Also re-injects the discipline reminder on the first prompt of a session (no
prior assistant turn recorded in the transcript yet), so labels land in the
first draft instead of being caught by the Stop hook after the fact.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import cast

READ_TIMEOUT_SECONDS = 5.0

DISCIPLINE_REMINDER = (
    "[discipline] Label every non-trivial claim (verified)/(inferred)/(guess). "
    "After multi-file changes include ## Did Not Verify listing what was not checked."
)


def read_stdin_payload(timeout: float = READ_TIMEOUT_SECONDS) -> str:
    """Read the hook's stdin JSON payload, bounded by a timeout.

    Backstops a hook orphaned past its parent's death: if nothing arrives
    within ``timeout`` seconds, returns "" instead of blocking forever.
    """
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if not ready:
        return ""
    return sys.stdin.read()


def git_branch(cwd: str) -> str:
    """Return the current git branch name, or "none" if it can't be determined."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "none"
    if result.returncode != 0:
        return "none"
    return result.stdout.rstrip("\n")


def has_prior_turns(transcript_path: str) -> bool:
    """Return whether the transcript file exists and has recorded content."""
    if not transcript_path:
        return False
    try:
        return Path(transcript_path).stat().st_size > 0
    except OSError:
        return False


def build_context(payload: str, cwd: str) -> str:
    """Build the ``[ctx]`` additionalContext string for a UserPromptSubmit event."""
    ctx = f"[ctx] {date.today():%Y-%m-%d} | cwd={cwd} | branch={git_branch(cwd)}"

    transcript_path = ""
    try:
        data: object = json.loads(payload) if payload else {}
    except json.JSONDecodeError:
        data = {}
    if isinstance(data, dict):
        payload_object = cast(dict[str, object], data)
        candidate = payload_object.get("transcript_path")
        if isinstance(candidate, str):
            transcript_path = candidate

    if not has_prior_turns(transcript_path):
        ctx = f"{ctx} | {DISCIPLINE_REMINDER}"
    return ctx


def main() -> int:
    """Print the UserPromptSubmit hookSpecificOutput JSON and return 0."""
    payload = read_stdin_payload()
    ctx = build_context(payload, os.getcwd())
    output = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}}
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
