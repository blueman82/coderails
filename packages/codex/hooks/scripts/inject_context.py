#!/usr/bin/env python3
"""Inject stable working-directory and branch context for UserPromptSubmit."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from typing import cast

from lib.context_manifest import route_for_payload, trace


def payload_object(raw_payload: str) -> dict[str, object]:
    """Return a mapping payload, treating malformed stdin as an empty mapping."""
    try:
        decoded: object = json.loads(raw_payload)
    except json.JSONDecodeError:
        return {}
    return cast(dict[str, object], decoded) if isinstance(decoded, dict) else {}


def branch_for(cwd: str) -> str:
    """Return the current branch, or the established ``none`` fallback."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "branch", "--show-current"],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return "none"
    return result.stdout.rstrip("\n") if result.returncode == 0 and result.stdout.rstrip("\n") else "none"


def main() -> int:
    """Emit the UserPromptSubmit additional-context JSON envelope."""
    raw = sys.stdin.read()
    payload = payload_object(raw)
    raw_cwd = payload.get("cwd")
    cwd = raw_cwd if isinstance(raw_cwd, str) and raw_cwd else os.getcwd()
    context = (
        f"[ctx] {date.today():%Y-%m-%d} | cwd={cwd} | branch={branch_for(cwd)} | "
        "[discipline] Label substantive claims (verified), (inferred), or (guess)."
    )
    hint, reason, session_id = route_for_payload(raw, "coderails-codex")
    if hint:
        context = f"{context} | {hint}"
    if reason != "route_none":  # ponytail: no row per unrouted prompt; unbounded trace growth for no signal
        trace("context_route", "ok" if hint else "fail_open", reason, session_id)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}}))
    return 0


if __name__ == "__main__":
    try:
        from lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("inject_context", main))
