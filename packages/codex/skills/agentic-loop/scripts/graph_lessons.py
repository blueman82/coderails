"""Read current cited lessons before a graph lock is acquired."""

from __future__ import annotations

import fcntl
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast


def query(progress: Path, push_script: Path, session: str) -> dict[str, Any]:
    """Run the provider's lesson reader against this graph's repo-key directory."""
    lock = Path(f"{progress}.lock")
    if lock.is_dir():
        raise ValueError("lessons query cannot run under the graph lock")
    if lock.is_file():
        with lock.open("r+", encoding="utf-8") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError("lessons query cannot run under the graph lock") from error
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)
    reader = push_script.parent / "lib/lessons.py"
    done = subprocess.run(
        [
            sys.executable,
            str(reader),
            "--dir",
            str(progress.parent.parent),
            "--session",
            session,
            "query",
            "--format",
            "contract",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        payload: object = json.loads(done.stdout)
    except (ValueError, TypeError) as error:
        raise ValueError("lessons reader returned invalid JSON") from error
    if done.returncode != 0:
        refusal = cast(dict[str, Any], payload) if isinstance(payload, dict) else {}
        raw = refusal.get("reason_code") or refusal.get("degraded")
        reason = raw if isinstance(raw, str) and raw else "unavailable"
        raise ValueError(f"lessons reader refused: {reason}")
    if not isinstance(payload, dict):
        raise ValueError("lessons reader returned a non-object")
    found = cast(dict[str, Any], payload)
    rows, digest = found.get("lessons"), found.get("sha256")
    if not isinstance(rows, list) or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("lessons reader returned an invalid contract")
    fields = {"id", "text", "cited", "cite", "quote", "muninn_id", "scope"}
    if not all(
        isinstance(row, dict)
        and set(cast(dict[str, Any], row)) == fields
        and isinstance(cast(dict[str, Any], row)["id"], str)
        and isinstance(cast(dict[str, Any], row)["text"], str)
        and bool(cast(dict[str, Any], row)["text"])
        and isinstance(cast(dict[str, Any], row)["cited"], bool)
        and all(isinstance(cast(dict[str, Any], row)[key], str) for key in ("cite", "quote", "scope"))
        and (cast(dict[str, Any], row)["muninn_id"] is None or isinstance(cast(dict[str, Any], row)["muninn_id"], str))
        for row in cast(list[object], rows)
    ):
        raise ValueError("lessons reader returned an invalid lesson row")
    calculated = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    if digest != calculated:
        raise ValueError("lessons reader returned a wrong digest")
    return {"lessons": rows, "sha256": digest}


def needed(state: dict[str, Any], authorization: bool = False) -> bool:
    """Select a current snapshot for assigned inputs or issued lesson-bearing contracts."""
    if authorization:
        return needed(state) or any(
            row.get("contract", {}).get("lessons_sha256") is not None
            for row in state["graph"].get("dispatches", {}).values()
        )
    return any(
        unit.get(key) for unit in state.get("work_units", {}).values() for key in ("manifest", "worktree", "lessons")
    )
