#!/usr/bin/env python3
"""Block repeated top-level full-suite and eval-ceremony runs per worktree."""

from __future__ import annotations

import json
import os
import re
import stat
import sys
import tempfile
from collections import Counter
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

from hook_common import append_trace_row, loop_state_path
from lib import argv_match
from lib.ceiling_key import mirror, worktree_key
from lib.dir_lock import acquire_dir_lock, release_dir_lock
from lib.shell_context import invocations, payload_cwd
from test_output import file_lock

SUITES = ("run_all.py", "run_all.sh", "test_codex_hooks.py")
CEREMONIES = ("validate-structure", "post")
PROGRESS_FIELD = {"full-suite": "run_all", "eval-ceremony": "post_evals"}
STATE_ERROR = "Verification-volume ceiling cannot create its state directory, so it is failing closed."
LOCK_ERROR = "Verification-volume ceiling could not acquire its worktree lock, so it is failing closed."
WRITE_ERROR = "Verification-volume ceiling could not update its count, so it is failing closed."


def payload_object(raw_payload: str) -> dict[str, object]:
    """Decode a hook payload, treating malformed input as an empty mapping."""
    try:
        decoded: object = json.loads(raw_payload)
    except json.JSONDecodeError:
        return {}
    return cast(dict[str, object], decoded) if isinstance(decoded, dict) else {}


def counted_invocations(command: str, cwd: str) -> list[tuple[str, str]]:
    """Return every counted action with its invocation-local directory."""
    found: list[tuple[str, str]] = []
    for _, argv, where in invocations(command, cwd):
        if argv_match.is_script(argv, SUITES):
            found.append((where, "full-suite"))
        elif argv_match.is_script(argv, "post_evals.py", CEREMONIES):
            found.append((where, "eval-ceremony"))
    return found


def deny(reason: str) -> None:
    """Emit the native PreToolUse denial envelope."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    with suppress(ImportError):  # telemetry must never be able to break the hook
        from lib.hook_telemetry import mark_deny

        mark_deny()


def count_for(count_path: Path) -> int:
    """Read a valid first-line counter, treating missing or corrupt state as zero."""
    try:
        first_line = count_path.read_text(encoding="utf-8").splitlines()[0]
    except (IndexError, OSError):
        return 0
    return int(first_line) if re.fullmatch(r"[0-9]+", first_line) else 0


def mirror_count(cwd: str, session: str, top: str, target: str, total: int) -> None:
    """Best-effort copy of the count into the matching progress.json work unit, under that file's lock."""
    path = loop_state_path(cwd, session) if session else None
    if path is None or not path.is_file():
        return
    temporary = ""
    try:
        with file_lock(Path(f"{path}.lock"), exclusive=True, blocking=False) as acquired:
            if not acquired:
                return
            mode = stat.S_IMODE(path.stat().st_mode)
            raw: object = json.loads(path.read_text(encoding="utf-8"))
            state = cast(dict[str, Any], raw) if isinstance(raw, dict) else {}
            if not mirror(state, top, PROGRESS_FIELD[target], total, session, os.environ.get("CLAUDE_LOOP_ID", "")):
                return
            with tempfile.NamedTemporaryFile(
                "w", dir=path.parent, prefix=f"{path.name}.tmp.", delete=False, encoding="utf-8"
            ) as stream:
                temporary = stream.name
                json.dump(state, stream, indent=2)
                stream.write("\n")
            os.chmod(temporary, mode)
            os.replace(temporary, path)
    except (OSError, ValueError):
        pass
    finally:
        if temporary:
            with suppress(OSError):
                Path(temporary).unlink()


def main() -> int:
    """Count eligible top-level runs and deny the third and later occurrence."""
    payload = payload_object(sys.stdin.read())
    tool_input = payload.get("tool_input")
    typed_tool_input = cast(dict[str, object], tool_input) if isinstance(tool_input, dict) else {}
    command = typed_tool_input.get("cmd", typed_tool_input.get("command"))
    if not isinstance(command, str) or isinstance(payload.get("agent_id"), str) and payload["agent_id"]:
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
    data_root = Path(os.environ.get("PLUGIN_DATA", str(Path.home() / ".coderails" / "codex")))
    state_dir = data_root / "verification-ceiling"
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        deny(STATE_ERROR)
        return 0

    paths = {key: state_dir / f"{key[0]}__{key[1]}.count" for key in amounts}
    locked: list[Path] = []
    session = payload.get("session_id")
    try:
        for path in sorted(paths.values()):
            lock = Path(f"{path}.lock")
            if not acquire_dir_lock(lock, 15, 0.1)[0]:
                deny(LOCK_ERROR)
                return 0
            locked.append(lock)
        totals = {key: count_for(path) + amounts[key] for key, path in paths.items()}
        exceeded = next((key for key, count in totals.items() if count >= 3), None)
        for key, path in paths.items():
            if exceeded and totals[key] < 3:
                continue
            try:
                path.write_text(f"{totals[key]}\n", encoding="utf-8")
            except OSError:
                deny(WRITE_ERROR)
                return 0
            top, cwd = contexts[key]
            mirror_count(cwd, session if isinstance(session, str) else "", top, key[1], totals[key])
    finally:
        for lock in reversed(locked):
            release_dir_lock(lock)

    if exceeded:
        top, _ = contexts[exceeded]
        target = exceeded[1]
        append_trace_row("argv", "denied", "ceiling_exceeded", session if isinstance(session, str) else "")
        deny(
            f"This is run {totals[exceeded]} of the same {target} in worktree '{top}'. "
            "The third and later full re-runs are blocked; use a focused check or "
            "delegate verification with spawn_agent."
        )
    return 0


if __name__ == "__main__":
    try:
        from lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("verification_volume_ceiling", main))
