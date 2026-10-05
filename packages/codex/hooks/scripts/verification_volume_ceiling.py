#!/usr/bin/env python3
"""Block repeated top-level full-suite and eval-ceremony runs per branch."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import cast

from lib.dir_lock import acquire_dir_lock, release_dir_lock

FULL_SUITE = re.compile(
    r"(^|[&;|])\s*(python3?\s+|\./)?([^\s]*/)?"
    r"(hooks/scripts/tests/run_all|packages/tests/test_codex_hooks)\.py(\s|$)"
)
EVAL_CEREMONY = re.compile(
    r"(^|[&;|])\s*(python3?\s+|\./)?([^\s]*/)?" r"scripts/post_evals\.py\s+validate-structure(\s|$)"
)
STATE_ERROR = "Verification-volume ceiling cannot create its state directory, so it is failing closed."
LOCK_ERROR = "Verification-volume ceiling could not acquire its branch lock, so it is failing closed."
WRITE_ERROR = "Verification-volume ceiling could not update its count, so it is failing closed."


def payload_object(raw_payload: str) -> dict[str, object]:
    """Decode a hook payload, treating malformed input as an empty mapping."""
    try:
        decoded: object = json.loads(raw_payload)
    except json.JSONDecodeError:
        return {}
    return cast(dict[str, object], decoded) if isinstance(decoded, dict) else {}


def target_for(command: object) -> str | None:
    """Return the counted command family, if the hook command is eligible."""
    if not isinstance(command, str):
        return None
    normalized = command.replace("\n", " ")
    if FULL_SUITE.search(normalized):
        return "full-suite"
    if EVAL_CEREMONY.search(normalized):
        return "eval-ceremony"
    return None


def payload_cwd(payload: dict[str, object]) -> str:
    """Return workdir, then cwd, then the process directory."""
    tool_input = payload.get("tool_input")
    typed_tool_input = cast(dict[str, object], tool_input) if isinstance(tool_input, dict) else {}
    workdir = typed_tool_input.get("workdir")
    if isinstance(workdir, str) and workdir:
        return workdir
    cwd = payload.get("cwd")
    return cwd if isinstance(cwd, str) and cwd else os.getcwd()


def branch_for(cwd: str) -> str:
    """Return the current branch or the established no-branch fallback."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "branch", "--show-current"],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return "no-branch"
    branch = result.stdout.rstrip("\n")
    return branch if result.returncode == 0 and branch else "no-branch"


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


def count_for(count_path: Path) -> int:
    """Read a valid first-line counter, treating missing or corrupt state as zero."""
    try:
        first_line = count_path.read_text(encoding="utf-8").splitlines()[0]
    except (IndexError, OSError):
        return 0
    return int(first_line) if re.fullmatch(r"[0-9]+", first_line) else 0


def main() -> int:
    """Count eligible top-level runs and deny the third and later occurrence."""
    payload = payload_object(sys.stdin.read())
    tool_input = payload.get("tool_input")
    typed_tool_input = cast(dict[str, object], tool_input) if isinstance(tool_input, dict) else {}
    command = typed_tool_input.get("cmd", typed_tool_input.get("command"))
    target = target_for(command)
    if target is None or isinstance(payload.get("agent_id"), str) and payload["agent_id"]:
        return 0

    branch = branch_for(payload_cwd(payload))
    branch_slug = branch.replace("/", "-").replace(" ", "-")
    data_root = Path(os.environ.get("PLUGIN_DATA", str(Path.home() / ".coderails" / "codex")))
    state_dir = data_root / "verification-ceiling"
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        deny(STATE_ERROR)
        return 0

    count_path = state_dir / f"{branch_slug}__{target}.count"
    lock_path = Path(f"{count_path}.lock")
    if not acquire_dir_lock(lock_path, 15, 0.1)[0]:
        deny(LOCK_ERROR)
        return 0
    try:
        count = count_for(count_path)
        try:
            count_path.write_text(f"{count + 1}\n", encoding="utf-8")
        except OSError:
            deny(WRITE_ERROR)
            return 0
    finally:
        release_dir_lock(lock_path)

    if count >= 2:
        deny(
            f"This is run {count + 1} of the same {target} on branch '{branch}'. "
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
