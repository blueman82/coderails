#!/usr/bin/env python3
"""Deny the third top-level full suite or validation ceremony per worktree."""

from __future__ import annotations

import copy
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import deny, read_payload
from hooks.scripts.lib import argv_match
from hooks.scripts.lib.agentic_loop_path import resolve_path
from hooks.scripts.lib.ceiling_key import mirror, worktree_key
from hooks.scripts.lib.dir_lock import acquire_dir_lock, release_dir_lock
from hooks.scripts.lib.loop_state_common import atomic_progress_update, read_state
from hooks.scripts.lib.shell_context import invocations, payload_cwd
from hooks.scripts.lib.trace_row import append_row

SUITES = ("run_all.py", "run_all.sh", "test_codex_hooks.py")
CEREMONIES = ("validate-structure", "post")


def target_for(command: str) -> str:
    """Return the counted target for an argv that runs a full suite or an eval ceremony, else an empty string."""
    for argv in argv_match.argvs(command):
        if argv_match.is_script(argv, SUITES):
            return "run_all"
        if argv_match.is_script(argv, "post_evals.py", CEREMONIES):
            return "post_evals"
    return ""


def mirror_count(cwd: str, session: object, top: str, target: str, total: int) -> None:
    """Best-effort copy of the count into the matching progress.json work unit, under that file's lock."""
    if not isinstance(session, str) or not session:
        return
    path = resolve_path(cwd, session)
    loop = os.environ.get("CLAUDE_LOOP_ID", "")
    if not mirror(copy.deepcopy(read_state(path)), top, target, total, session, loop):
        return

    def update(data: dict[str, Any]) -> dict[str, Any]:
        if not mirror(data, top, target, total, session, loop):
            raise ValueError("optional mirror ownership changed before the locked read")
        return data

    atomic_progress_update(path, update)


def main() -> int:
    """Deny a third top-level full-suite or validation invocation per worktree."""
    payload = read_payload()
    data = payload.get("tool_input")
    command = data.get("command", "") if isinstance(data, dict) else ""
    target = target_for(command) if isinstance(command, str) else ""
    if not isinstance(command, str) or not target or isinstance(payload.get("agent_id"), str) and payload["agent_id"]:
        return 0
    cwd = next(
        where
        for _, argv, where in invocations(command, payload_cwd(payload))
        if argv_match.is_script(argv, SUITES) or argv_match.is_script(argv, "post_evals.py", CEREMONIES)
    )
    digest, top = worktree_key(cwd)
    state = (
        Path(os.environ.get("CLAUDE_AGENTIC_LOOP_DIR", str(Path.home() / ".coderails/agentic-loop")))
        / "verification-ceiling"
    )
    try:
        state.mkdir(parents=True, exist_ok=True)
    except OSError:
        deny("Verification-volume ceiling: could not create its state directory; failing closed.")
        return 0
    count_file = state / f"{digest}__{target}.count"
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
        mirror_count(cwd, payload.get("session_id"), top, target, count + 1)
    finally:
        release_dir_lock(lock)
    if count >= 2:
        append_row("argv", "denied", "ceiling_exceeded", str(payload.get("session_id") or "?"), inputs={"top": top})
        deny(
            f"Verification-volume ceiling: this is the {count + 1}th invocation of {target} in "
            f"worktree '{top}' — the 3rd+ re-run is hard-blocked."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
