"""Validate additive contained-source receipts within existing driver evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import graph_driver_process


def _digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("driver transfer artifact is missing or a symlink")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError("driver transfer artifact is invalid")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("driver transfer artifact is invalid")
    return cast(dict[str, Any], value)


def _json_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def claim(
    artifact: Path,
    state: dict[str, Any],
    record: dict[str, Any],
    identifier: str,
    checkout: Path,
    provider: str,
    exit_code: int,
    result: dict[str, Any],
    *,
    required: bool = False,
) -> dict[str, str]:
    """Recheck fixed receipt identities without reading execution clone C or later root edits in D."""
    if provider != "claude":
        if required:
            raise ValueError("driver transfer belongs to Claude")
        return {}
    marker = re.search(rb"\nWorkspace SHA256: ([0-9a-f]{64})\n", (artifact / "prompt.txt").read_bytes())
    if marker is None:
        if required or (artifact / "workspace.json").exists():
            raise ValueError("driver transfer lacks its authorized workspace mapping")
        return {}
    workspace = _object(artifact / "workspace.json")
    receipt = _object(artifact / "transfer.json")
    expected = {
        "session_id": state["session_id"],
        "loop_id": state["loop_id"],
        "node_id": record["node_id"],
        "dispatch_id": identifier,
        "revision": record["revision"],
        "wave_id": record["wave_id"],
        "attempt": record["attempt"],
        "contract_sha256": _json_digest(record["contract"]),
    }
    for value in (workspace, receipt):
        if any(value.get(key) != item for key, item in expected.items()):
            raise ValueError("driver transfer is foreign or stale")
        if value.get("destination") != str(checkout.resolve(strict=True)):
            raise ValueError("driver transfer destination changed")
    workspace_sha = _digest(artifact / "workspace.json")
    if marker.group(1).decode() != workspace_sha or receipt.get("workspace_sha256") != workspace_sha:
        raise ValueError("driver transfer workspace changed")
    if (
        workspace.get("execution") == workspace.get("destination")
        or not Path(workspace["execution"]).is_absolute()
        or receipt.get("prompt_sha256") != record["authorized"]["prompt_sha256"]
        or receipt.get("driver_run_id") != record["authorized"]["driver_run_id"]
        or receipt.get("output_sha256") != _digest(artifact / "output.jsonl")
        or receipt.get("exit_code") != exit_code
        or receipt.get("head_at_exit") != graph_driver_process.exit_head(artifact, exit_code)
        or receipt.get("head_at_exit") != workspace.get("head")
        or receipt.get("journal_sha256") != _digest(artifact / "transfer-journal.json")
    ):
        raise ValueError("driver transfer terminal binding changed")
    worker_result = receipt.get("worker_result")
    if receipt.get("result_sha256") != _json_digest(worker_result):
        raise ValueError("driver transfer result changed")
    if result != worker_result:
        refused = {
            "outcome": "failed",
            "evidence": "driver_transfer_quarantined:" + receipt.get("reason", ""),
            "final_report": None,
        }
        if receipt.get("status") != "quarantined" or result != refused:
            raise ValueError("driver transfer admitted result changed")
    capture_file = artifact / "capture.json"
    capture_sha = _digest(capture_file) if capture_file.exists() else None
    if receipt.get("capture_sha256") != capture_sha:
        raise ValueError("driver transfer capture changed")
    if receipt.get("status") == "materialized":
        proposed = _object(capture_file)
        for key in (
            *expected,
            "workspace_sha256",
            "destination",
            "driver_run_id",
            "prompt_sha256",
            "output_sha256",
            "exit_code",
            "worker_result",
            "result_sha256",
            "head_at_exit",
        ):
            if proposed.get(key) != receipt.get(key):
                raise ValueError("driver transfer proposal binding changed")
    elif receipt.get("status") != "quarantined" or result.get("outcome") in {"done", "skipped"}:
        raise ValueError("driver transfer was not completed")
    return {"workspace_sha256": workspace_sha, "transfer_sha256": _digest(artifact / "transfer.json")}


def prepublication_claim(
    state_path: Path,
    state: dict[str, Any],
    node_id: str,
    dispatch_id: str,
    checkout: Path,
    provider: str,
    exit_code: int,
    result: dict[str, Any],
    *,
    record: dict[str, Any],
) -> dict[str, Any]:
    """Bind one finished worker result before root publication can proceed."""
    artifact = state_path.parent / "driver-evidence" / dispatch_id
    prompt_sha256 = _digest(artifact / "prompt.txt")
    if prompt_sha256 != record["authorized"]["prompt_sha256"]:
        raise ValueError("driver prompt differs from its authorization")
    if provider not in {"codex", "claude"} or type(exit_code) is not int:
        raise ValueError("invalid worker result metadata")
    return {
        "session_id": state.get("session_id"),
        "loop_id": state.get("loop_id"),
        "node_id": node_id,
        "dispatch_id": dispatch_id,
        "wave_id": record["wave_id"],
        "attempt": record["attempt"],
        "driver_run_id": record["authorized"]["driver_run_id"],
        "provider": provider,
        "checkout": str(checkout.resolve(strict=True)),
        "prompt_sha256": prompt_sha256,
        "output_sha256": _digest(artifact / "output.jsonl"),
        "final_sha256": _digest(artifact / "final.json") if provider == "codex" else None,
        "exit_code": exit_code,
        "result": result,
        **claim(artifact, state, record, dispatch_id, checkout, provider, exit_code, result),
    }


Finish = Callable[[Path, dict[str, Any], str, dict[str, Any], Path, int, dict[str, Any]], dict[str, Any]]


def finish(
    progress: Path,
    state: dict[str, Any],
    identifier: str,
    checkout: Path,
    code: int,
    result: dict[str, Any],
    callback: Finish | None,
) -> dict[str, Any]:
    """Admit a transfer failure through the existing worker result channel."""
    if callback is None:
        return result
    receipt = callback(progress, state, identifier, state["graph"]["dispatches"][identifier], checkout, code, result)
    if receipt["status"] != "materialized" and result.get("outcome") in {"done", "skipped"}:
        return {
            "outcome": "failed",
            "evidence": "driver_transfer_quarantined:" + receipt["reason"],
            "final_report": None,
        }
    return result


def artifact(state_path: Path, dispatch_id: str) -> Path:
    """Return the existing owned driver attempt directory."""
    return state_path.parent / "driver-evidence" / dispatch_id
