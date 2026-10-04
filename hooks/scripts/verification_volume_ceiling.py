#!/usr/bin/env python3
"""Deny the third top-level full suite or validation ceremony per branch."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import deny, read_payload
from hooks.scripts.lib.dir_lock import acquire_dir_lock, release_dir_lock

RUN_ALL = re.compile(
    r"(^|[&;|])\s*(?:(?:bash|sh|python3?)\s+|\./)?(?:\S*/)?hooks/scripts/tests/run_all\.(?:sh|py)(?:\s|$)"
)
POST = re.compile(
    r"(^|[&;|])\s*(?:(?:bash|sh|python3?)\s+|\./)?(?:\S*/)?scripts/post_evals\.(?:sh|py)\s+validate-structure(?:\s|$)"
)


def main() -> int:
    """Deny a third top-level full-suite or validation invocation per branch."""
    payload = read_payload()
    data = payload.get("tool_input")
    command = data.get("command", "") if isinstance(data, dict) else ""
    target = (
        "run_all"
        if isinstance(command, str) and RUN_ALL.search(command.replace("\n", " "))
        else "post_evals" if isinstance(command, str) and POST.search(command.replace("\n", " ")) else ""
    )
    if not target or isinstance(payload.get("agent_id"), str) and payload["agent_id"]:
        return 0
    cwd_value = payload.get("cwd")
    cwd = cwd_value if isinstance(cwd_value, str) else os.getcwd()
    branch = (
        subprocess.run(
            ["git", "-C", cwd, "branch", "--show-current"], capture_output=True, text=True, check=False
        ).stdout.strip()
        or "(no-branch)"
    )
    state = (
        Path(os.environ.get("CLAUDE_AGENTIC_LOOP_DIR", str(Path.home() / ".coderails/agentic-loop")))
        / "verification-ceiling"
    )
    try:
        state.mkdir(parents=True, exist_ok=True)
    except OSError:
        deny("Verification-volume ceiling: could not create its state directory; failing closed.")
        return 0
    count_file = state / f"{branch.replace('/', '-')}__{target}.count"
    lock = Path(f"{count_file}.lock")
    if not acquire_dir_lock(lock, 15, 0.1)[0]:
        deny("Verification-volume ceiling: could not acquire its per-target lock; failing closed.")
        return 0
    try:
        try:
            raw = count_file.read_text().strip()
            count = int(raw) if raw.isdigit() else 0
        except OSError:
            count = 0
        try:
            count_file.write_text(str(count + 1), encoding="utf-8")
        except OSError:
            deny("Verification-volume ceiling: could not write its count file; failing closed.")
            return 0
    finally:
        release_dir_lock(lock)
    if count >= 2:
        deny(
            f"Verification-volume ceiling: this is the {count + 1}th invocation of {target} on "
            f"work-unit branch '{branch}' — the 3rd+ re-run is hard-blocked."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
