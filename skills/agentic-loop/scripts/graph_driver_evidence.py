"""Seal and revalidate raw evidence for one driver worker attempt."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Optional, cast

import graph_semantics

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
    first = graph.get("driver_from_revision")
    last = graph.get("native_last_revision")
    if graph.get("dispatch_mode") != "driver" or type(first) is not int or type(last) is not int or first != last + 2:
        raise ValueError("driver cutover is missing or invalid")
    dispatches = cast(dict[str, Any], graph.get("dispatches", {}))
    record = cast(Optional[dict[str, Any]], dispatches.get(dispatch_id))
    if not isinstance(record, dict) or record.get("node_id") != node_id:
        raise ValueError("foreign driver dispatch")
    if record.get("dispatch_mode") != "driver":
        raise ValueError("dispatch is not driver owned")
    if not isinstance(record.get("authorized"), dict) or not record["authorized"].get("driver_run_id"):
        raise ValueError("driver dispatch was not authorized")
    if re.fullmatch(r"[0-9a-f]{64}", str(record["authorized"].get("prompt_sha256", ""))) is None:
        raise ValueError("driver authorization lacks a prompt digest")
    for key in ("wave_id", "revision", "attempt", "task_name"):
        if not record.get(key):
            raise ValueError(f"driver dispatch lacks {key}")
    if type(record["revision"]) is not int or record["revision"] < first:
        raise ValueError("driver dispatch precedes cutover")
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
    prompt_sha256 = _digest(artifact / "prompt.txt")
    if prompt_sha256 != record["authorized"]["prompt_sha256"]:
        raise ValueError("driver prompt differs from its authorization")
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
        "prompt_sha256": prompt_sha256,
        "output_sha256": _digest(artifact / "output.jsonl"),
        "exit_code": exit_code,
        "result": result,
    }
    if provider == "codex":
        manifest["final_sha256"] = _digest(artifact / "final.json")
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


def validate(state_path: Path, state: dict[str, Any], node_id: str, reference: dict[str, Any]) -> dict[str, Any]:
    """Reject changed, missing, replayed or foreign worker evidence."""
    if (
        set(reference) != {"kind", "dispatch_id", "wave_id", "attempt", "manifest_sha256"}
        or reference.get("kind") != "driver_worker"
    ):
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
    if manifest.get("prompt_sha256") != record["authorized"]["prompt_sha256"]:
        raise ValueError("driver prompt differs from its authorization")
    if _digest(artifact / "prompt.txt") != manifest.get("prompt_sha256"):
        raise ValueError("driver prompt changed")
    if _digest(artifact / "output.jsonl") != manifest.get("output_sha256"):
        raise ValueError("driver output changed")
    if manifest.get("provider") == "codex" and _digest(artifact / "final.json") != manifest.get("final_sha256"):
        raise ValueError("driver final result changed")
    checkout = manifest.get("checkout")
    if not isinstance(checkout, str) or _head(Path(checkout)) != manifest.get("head"):
        raise ValueError("worker checkout HEAD changed")
    return cast(dict[str, Any], manifest)


def apply_record(state_path: Path, state: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """Apply one complete driver wave only after rechecking each sealed result."""
    if state["graph"].get("dispatch_mode") != "driver" or set(report) != {"wave_id", "results", "references"}:
        raise ValueError("driver wave report has invalid mode or fields")
    validate_backup(state_path, state)
    active_value: object = state["graph"].get("active_wave")
    if not isinstance(active_value, dict):
        raise ValueError("driver graph has no active wave")
    active = cast(dict[str, Any], active_value)
    nodes = set(cast(list[str], active["nodes"]))
    results_value: object = report["results"]
    references_value: object = report["references"]
    if not isinstance(results_value, dict) or not isinstance(references_value, dict):
        raise ValueError("driver wave requires result and reference objects")
    results = cast(dict[str, Any], results_value)
    references = cast(dict[str, Any], references_value)
    if set(results) != nodes or set(references) != nodes:
        raise ValueError("driver wave requires every result and reference")
    transition = graph_semantics.record_wave(state, report["wave_id"], results)
    proposed = cast(dict[str, Any], transition["state"])
    for node_id in sorted(nodes):
        reference = references[node_id]
        if not isinstance(reference, dict):
            raise ValueError("driver evidence reference must be an object")
        manifest = validate(state_path, state, node_id, cast(dict[str, Any], reference))
        if manifest.get("result") != results[node_id]:
            raise ValueError("driver result differs from sealed worker output")
        if results[node_id]["outcome"] in {"done", "skipped"} and manifest.get("exit_code") != 0:
            raise ValueError("successful driver result has a failing process exit")
        proposed["graph"]["nodes"][node_id]["evidence"].append(reference)
    validate_history(state_path, proposed)
    return transition


def validate_history(state_path: Path, state: dict[str, Any]) -> None:
    """Re-read each retained driver attempt and require one reference per finished dispatch."""
    graph = cast(dict[str, Any], state["graph"])
    if graph.get("dispatch_mode") != "driver":
        raise ValueError("driver cutover is missing")
    first = graph["driver_from_revision"]
    dispatches = cast(dict[str, Any], graph.get("dispatches", {}))
    seen: set[str] = set()
    for node_id, node in cast(dict[str, Any], graph["nodes"]).items():
        for item in cast(list[Any], node["evidence"]):
            if not isinstance(item, dict):
                continue
            reference = cast(dict[str, Any], item)
            if reference.get("kind") != "driver_worker":
                continue
            dispatch_id = reference.get("dispatch_id")
            if not isinstance(dispatch_id, str) or dispatch_id in seen:
                raise ValueError("duplicate or invalid driver evidence")
            seen.add(dispatch_id)
            validate(state_path, state, node_id, reference)
    active = cast(Optional[dict[str, Any]], graph.get("active_wave"))
    for dispatch_id, value in dispatches.items():
        record = cast(dict[str, Any], value)
        revision = record.get("revision")
        if type(revision) is not int or revision < first:
            continue
        if record.get("dispatch_mode") != "driver":
            raise ValueError("native dispatch exists after driver cutover")
        if active is not None and record.get("wave_id") == active.get("wave_id"):
            if dispatch_id in seen:
                raise ValueError("active driver dispatch already has stored evidence")
            continue
        if dispatch_id not in seen:
            raise ValueError("finished driver dispatch is missing evidence")


def validate_backup(state_path: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Check the sealed native snapshot and unchanged native history prefix."""
    graph = cast(dict[str, Any], state["graph"])
    backup = state_path.with_name("progress.json.pre-driver")
    if _digest(backup) != graph.get("native_backup_sha256"):
        raise ValueError("native backup changed")
    try:
        parsed: object = json.loads(backup.read_bytes())
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("native backup is invalid JSON") from error
    if not isinstance(parsed, dict):
        raise ValueError("native backup is not an object")
    old = cast(dict[str, Any], parsed)
    if (
        old.get("session_id") != state.get("session_id")
        or old.get("loop_id") != state.get("loop_id")
        or old.get("revision") != graph.get("native_last_revision")
    ):
        raise ValueError("native backup belongs to another graph")
    old_graph_value: object = old.get("graph")
    if not isinstance(old_graph_value, dict):
        raise ValueError("native backup has an invalid graph")
    old_graph = cast(dict[str, Any], old_graph_value)
    if old_graph.get("dispatch_mode") is not None:
        raise ValueError("native backup has an invalid graph")
    for dispatch_id, record in cast(dict[str, Any], old_graph.get("dispatches", {})).items():
        if graph.get("dispatches", {}).get(dispatch_id) != record:
            raise ValueError("native dispatch history changed")
    for node_id, node in cast(dict[str, Any], old_graph["nodes"]).items():
        current = cast(dict[str, Any], graph["nodes"].get(node_id, {}))
        prior_evidence = cast(list[Any], node["evidence"])
        if current.get("evidence", [])[: len(prior_evidence)] != prior_evidence:
            raise ValueError("native evidence history changed")
    return old
