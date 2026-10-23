"""Seal and revalidate raw evidence for one driver worker attempt."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Optional, cast

_DISPATCH_ID = re.compile(r"[a-zA-Z0-9_-]{1,100}\Z")


def _digest(path: Path) -> str:
    """Hash the exact bytes at a regular artifact path."""
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or invalid {path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _head(checkout: Path) -> str:
    """Read the exact commit at the worker checkout."""
    result = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    head = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"[0-9a-f]{40,64}", head):
        raise ValueError("worker checkout HEAD is unavailable")
    return head


def _record(state: dict[str, Any], node_id: str, dispatch_id: str) -> dict[str, Any]:
    """Require an authorized driver record owned by this graph and node."""
    if not _DISPATCH_ID.fullmatch(dispatch_id):
        raise ValueError("invalid dispatch id")
    if state.get("graph") is None:
        raise ValueError("driver graph is missing")
    graph = cast(dict[str, Any], state["graph"])
    dispatches = cast(dict[str, Any], graph.get("dispatches", {}))
    record = cast(Optional[dict[str, Any]], dispatches.get(dispatch_id))
    if not isinstance(record, dict) or record.get("node_id") != node_id:
        raise ValueError("foreign driver dispatch")
    if record.get("dispatch_mode") != "driver":
        raise ValueError("dispatch is not driver owned")
    if not isinstance(record.get("authorized"), dict) or not record["authorized"].get("driver_run_id"):
        raise ValueError("driver dispatch was not authorized")
    for key in ("wave_id", "revision", "attempt", "task_name"):
        if not record.get(key):
            raise ValueError(f"driver dispatch lacks {key}")
    return record


def _artifact(state_path: Path, dispatch_id: str) -> Path:
    """Use a fixed artifact directory under the owned graph directory."""
    return state_path.parent / "driver-evidence" / dispatch_id


def seal(
    state_path: Path,
    state: dict[str, Any],
    node_id: str,
    dispatch_id: str,
    checkout: Path,
    provider: str,
    exit_code: int,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Write a manifest once and return a compact graph reference."""
    record = _record(state, node_id, dispatch_id)
    if provider not in {"codex", "claude"} or type(exit_code) is not int:
        raise ValueError("invalid worker result metadata")
    artifact = _artifact(state_path, dispatch_id)
    manifest_path = artifact / "manifest.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        raise ValueError("driver evidence was already sealed")
    manifest = {
        "session_id": state.get("session_id"),
        "loop_id": state.get("loop_id"),
        "node_id": node_id,
        "dispatch_id": dispatch_id,
        "wave_id": record["wave_id"],
        "revision": record["revision"],
        "attempt": record["attempt"],
        "task_name": record["task_name"],
        "driver_run_id": record["authorized"]["driver_run_id"],
        "provider": provider,
        "checkout": str(checkout.resolve(strict=True)),
        "head": _head(checkout),
        "prompt_sha256": _digest(artifact / "prompt.txt"),
        "output_sha256": _digest(artifact / "output.jsonl"),
        "exit_code": exit_code,
        "result": result,
    }
    data = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    with manifest_path.open("xb") as stream:
        stream.write(data)
    reference = {
        "kind": "driver_worker",
        "dispatch_id": dispatch_id,
        "wave_id": record["wave_id"],
        "attempt": record["attempt"],
        "manifest_sha256": hashlib.sha256(data).hexdigest(),
    }
    validate(state_path, state, node_id, reference)
    return reference


def validate(state_path: Path, state: dict[str, Any], node_id: str, reference: dict[str, Any]) -> None:
    """Reject changed, missing, replayed or foreign worker evidence."""
    if reference.get("kind") != "driver_worker":
        raise ValueError("invalid driver evidence reference")
    dispatch_id = reference.get("dispatch_id")
    if not isinstance(dispatch_id, str):
        raise ValueError("invalid driver evidence dispatch id")
    record = _record(state, node_id, dispatch_id)
    if reference.get("wave_id") != record["wave_id"] or reference.get("attempt") != record["attempt"]:
        raise ValueError("driver evidence belongs to another wave or attempt")
    artifact = _artifact(state_path, dispatch_id)
    manifest_path = artifact / "manifest.json"
    digest = _digest(manifest_path)
    if digest != reference.get("manifest_sha256"):
        raise ValueError("driver manifest changed")
    try:
        manifest = json.loads(manifest_path.read_bytes())
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("invalid driver manifest") from error
    expected = {
        "session_id": state.get("session_id"),
        "loop_id": state.get("loop_id"),
        "node_id": node_id,
        "dispatch_id": dispatch_id,
        "wave_id": record["wave_id"],
        "revision": record["revision"],
        "attempt": record["attempt"],
        "task_name": record["task_name"],
        "driver_run_id": record["authorized"]["driver_run_id"],
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("foreign or replayed driver manifest")
    if _digest(artifact / "prompt.txt") != manifest.get("prompt_sha256"):
        raise ValueError("driver prompt changed")
    if _digest(artifact / "output.jsonl") != manifest.get("output_sha256"):
        raise ValueError("driver output changed")
    checkout = manifest.get("checkout")
    if not isinstance(checkout, str) or _head(Path(checkout)) != manifest.get("head"):
        raise ValueError("worker checkout HEAD changed")
