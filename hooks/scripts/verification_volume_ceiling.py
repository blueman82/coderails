#!/usr/bin/env python3
"""Deny the third top-level full suite or validation ceremony per worktree."""

from __future__ import annotations

import copy
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import deny, read_payload
from hooks.scripts.lib import argv_match
from hooks.scripts.lib.agentic_loop_path import resolve_path
from hooks.scripts.lib.ceiling_key import legacy_key, mirror, worktree_key
from hooks.scripts.lib.dir_lock import acquire_dir_lock, release_dir_lock
from hooks.scripts.lib.loop_state_common import atomic_progress_update, read_state
from hooks.scripts.lib.shell_context import invocations, opaque_execution, payload_cwd
from hooks.scripts.lib.trace_row import append_row

SUITES = ("run_all.py", "run_all.sh", "test_codex_hooks.py")
CEREMONIES = ("validate-structure", "post")


def counted_invocations(command: str, cwd: str) -> list[tuple[str, str]]:
    """Return every counted action with its invocation-local directory."""
    found: list[tuple[str, str]] = []
    for _, argv, where in invocations(command, cwd):
        if argv_match.is_script(argv, SUITES):
            found.append((where, "run_all"))
        elif argv_match.is_script(argv, "post_evals.py", CEREMONIES):
            found.append((where, "post_evals"))
    return found


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
    if not isinstance(command, str) or isinstance(payload.get("agent_id"), str) and payload["agent_id"]:
        return 0
    if opaque_execution(command, payload_cwd(payload)):
        deny("Verification-volume ceiling: executable shell body exceeds the guarded parser depth.")
        return 0
    found = counted_invocations(command, payload_cwd(payload))
    if not found:
        return 0
    contexts: dict[tuple[str, str], tuple[str, str]] = {}
    amounts: Counter[tuple[str, str]] = Counter()
    for cwd, target in found:
        digest, top = worktree_key(cwd)
        key = (digest, target)
        contexts[key] = (top, cwd)
        amounts[key] += 1
    state = (
        Path(os.environ.get("CLAUDE_AGENTIC_LOOP_DIR", str(Path.home() / ".coderails/agentic-loop")))
        / "verification-ceiling"
    )
    try:
        state.mkdir(parents=True, exist_ok=True)
    except OSError:
        deny("Verification-volume ceiling: could not create its state directory; failing closed.")
        return 0
    paths = {key: state / f"{key[0]}__{key[1]}.count" for key in amounts}
    legacy_paths = {key: state / legacy_key(contexts[key][1], key[1]) for key in amounts}
    locked: list[Path] = []
    try:
        for path in sorted(set(paths.values()) | set(legacy_paths.values())):
            lock = Path(f"{path}.lock")
            if not acquire_dir_lock(lock, 15, 0.1)[0]:
                deny("Verification-volume ceiling: could not acquire its per-target lock; failing closed.")
                return 0
            locked.append(lock)
        totals: dict[tuple[str, str], int] = {}
        migrated: set[tuple[str, str]] = set()
        for key, path in paths.items():
            source = path
            if not path.exists():
                source = legacy_paths[key]
                if source.exists():
                    migrated.add(key)
            try:
                raw = source.read_text().strip()
                count = int(raw) if raw.isdigit() else 0
            except OSError:
                count = 0
            totals[key] = count + amounts[key]
        exceeded = next((key for key, count in totals.items() if count >= 3), None)
        for key, path in paths.items():
            if exceeded and totals[key] < 3:
                continue
            try:
                legacy = legacy_paths[key]
                if legacy.exists():
                    previous = legacy.read_text().strip()
                    legacy.write_text(
                        str(max(int(previous) if previous.isdigit() else 0, totals[key])), encoding="utf-8"
                    )
                path.write_text(str(totals[key]), encoding="utf-8")
            except OSError:
                deny("Verification-volume ceiling: could not write its count file; failing closed.")
                return 0
            top, cwd = contexts[key]
            if key in migrated:
                append_row("argv", "allowed", "ceiling_legacy_migrated", str(payload.get("session_id") or "?"))
            mirror_count(cwd, payload.get("session_id"), top, key[1], totals[key])
    finally:
        for lock in reversed(locked):
            release_dir_lock(lock)
    if exceeded:
        top, _ = contexts[exceeded]
        target = exceeded[1]
        append_row("argv", "denied", "ceiling_exceeded", str(payload.get("session_id") or "?"), inputs={"top": top})
        deny(
            f"Verification-volume ceiling: this is the {totals[exceeded]}th invocation of {target} in "
            f"worktree '{top}' — the 3rd+ re-run is hard-blocked."
        )
    return 0


if __name__ == "__main__":
    try:
        from hooks.scripts.lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("verification_volume_ceiling", main))
