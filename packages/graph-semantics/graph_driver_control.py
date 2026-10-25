"""Bind root-owned graph results to durable files without dispatching a worker."""

from __future__ import annotations

import copy
import hashlib
import json
import secrets
from pathlib import Path
from typing import Any, cast

import graph_semantics
import graph_spec

_MAX_RESULT_BYTES = 1_000_000


def append_scope_note(
    state: dict[str, Any],
    session: str,
    loop_id: str,
    revision: int,
    unit: str,
    expected_scope_sha256: str,
    note: str,
    reason: str,
) -> dict[str, Any]:
    """Append a nonfrozen note to a pending unit without changing earlier evidence."""
    graph = cast(dict[str, Any], state["graph"])
    units = cast(dict[str, Any], state.get("work_units", {}))
    raw_record = units.get(unit)
    raw_node = cast(dict[str, Any], graph["nodes"]).get(f"U3[{unit}]")
    record = cast(dict[str, Any], raw_record) if isinstance(raw_record, dict) else None
    node = cast(dict[str, Any], raw_node) if isinstance(raw_node, dict) else None
    if (state.get("session_id"), state.get("loop_id"), state.get("revision")) != (session, loop_id, revision):
        raise ValueError("scope note owner or revision changed")
    if state.get("status") != "in-progress" or graph.get("dispatch_mode") != "driver":
        raise ValueError("scope note requires an active driver loop")
    if graph.get("active_wave") is not None or graph.get("hard_stop") is not None:
        raise ValueError("scope note requires an idle graph")
    if (
        not isinstance(record, dict)
        or record.get("status") != "pending"
        or not isinstance(node, dict)
        or node.get("status") != "pending"
    ):
        raise ValueError("scope note requires a pending unit and node")
    old_scope = record.get("scope")
    if not isinstance(old_scope, str) or not old_scope.strip() or not note.strip() or not reason.strip():
        raise ValueError("scope note requires a task, note and reason")
    old_sha = hashlib.sha256(old_scope.encode("utf-8")).hexdigest()
    if not secrets.compare_digest(old_sha, expected_scope_sha256):
        raise ValueError("scope note expected scope hash changed")
    if not isinstance(record.get("scope_notes", []), list):
        raise ValueError("scope note audit history is invalid")
    new_scope = f"{old_scope}\n\n[Nonfrozen scope note]\nReason: {reason.strip()}\nNote: {note.strip()}"
    proposed = copy.deepcopy(state)
    saved = proposed["work_units"][unit]
    saved["scope"] = new_scope
    saved.setdefault("scope_notes", []).append(
        {
            "revision": state["revision"] + 1,
            "old_sha256": old_sha,
            "new_sha256": hashlib.sha256(new_scope.encode("utf-8")).hexdigest(),
            "reason": reason.strip(),
            "note": note.strip(),
            "nonfrozen": True,
        }
    )
    proposed["revision"] += 1
    graph_semantics.validate(proposed)
    return proposed


def _artifact(path: Path, wave_id: str, node_id: str) -> Path:
    digest = hashlib.sha256(f"{wave_id}|{node_id}".encode()).hexdigest()[:24]
    return path.parent / "driver-control" / digest / "manifest.json"


def _digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("root control result file is missing or a symlink")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _result(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("root control result must be an object")
    result = cast(dict[str, Any], value)
    if (
        set(result) != {"outcome", "evidence"}
        or result["outcome"] not in {"done", "skipped", "failed"}
        or not isinstance(result["evidence"], str)
        or not result["evidence"].strip()
    ):
        raise ValueError("root control result has invalid fields")
    return cast(dict[str, str], result)


def _owned(state: dict[str, Any], node_id: str) -> dict[str, Any]:
    graph = cast(dict[str, Any], state["graph"])
    active = graph.get("active_wave")
    spec = graph_spec.load_spec()
    node = graph_spec.node_for(spec, node_id)
    if (
        graph.get("dispatch_mode") != "driver"
        or not isinstance(active, dict)
        or node_id not in active["nodes"]
        or node is None
        or node["agent_role"] is not None
    ):
        raise ValueError("root control result does not own an active control node")
    dispatches = cast(dict[str, dict[str, object]], graph.get("dispatches", {}))
    wave_id = cast(str, active["wave_id"])
    if any(record.get("wave_id") == wave_id and record.get("node_id") == node_id for record in dispatches.values()):
        raise ValueError("root control node has a worker dispatch")
    return cast(dict[str, Any], active)


def stage(path: Path, state: dict[str, Any], session: str, node_id: str, result_file: Path) -> dict[str, Any]:
    """Stage one exact root result; progress.json is not changed."""
    if state.get("session_id") != session:
        raise ValueError("root control result belongs to another session")
    active = _owned(state, node_id)
    if result_file.stat().st_size > _MAX_RESULT_BYTES:
        raise ValueError("root control result file is too large")
    result_path = result_file.resolve(strict=True)
    result = _result(json.loads(result_file.read_text(encoding="utf-8")))
    manifest = {
        "session_id": session,
        "loop_id": state["loop_id"],
        "wave_id": active["wave_id"],
        "revision": active["revision"],
        "node_id": node_id,
        "result_file": str(result_path),
        "result_sha256": _digest(result_file),
        "result": result,
    }
    data = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    target = _artifact(path, active["wave_id"], node_id)
    if target.parent.parent.is_symlink() or target.parent.is_symlink() or target.is_symlink():
        raise ValueError("root control artifact path is a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != data:
            raise ValueError("root control result already differs")
    else:
        with target.open("xb") as stream:
            stream.write(data)
    reference = {
        "kind": "root_control",
        "wave_id": active["wave_id"],
        "node_id": node_id,
        "manifest_sha256": hashlib.sha256(data).hexdigest(),
    }
    validate(path, state, node_id, reference)
    return reference


def validate(path: Path, state: dict[str, Any], node_id: str, reference: dict[str, Any]) -> dict[str, Any]:
    """Re-read a root result and its source file at every later graph check."""
    node = graph_spec.node_for(graph_spec.load_spec(), node_id)
    if node is None or node["agent_role"] is not None:
        raise ValueError("root control reference belongs to a worker node")
    if (
        set(reference) != {"kind", "wave_id", "node_id", "manifest_sha256"}
        or reference.get("kind") != "root_control"
        or reference.get("node_id") != node_id
        or not isinstance(reference.get("wave_id"), str)
    ):
        raise ValueError("invalid root control reference")
    graph = cast(dict[str, Any], state["graph"])
    active_value = graph.get("active_wave")
    active = cast(dict[str, Any], active_value) if isinstance(active_value, dict) else None
    if active is not None and reference["wave_id"] == active.get("wave_id"):
        if node_id not in active.get("nodes", []):
            raise ValueError("root control result belongs to another wave")
        current_revision = active.get("revision")
    else:
        node = cast(dict[str, Any], graph["nodes"][node_id])
        if reference not in node.get("evidence", []):
            raise ValueError("root control result belongs to another wave")
        current_revision = None
    target = _artifact(path, reference["wave_id"], node_id)
    if target.is_symlink() or not target.is_file():
        raise ValueError("root control manifest is missing or a symlink")
    data = target.read_bytes()
    if hashlib.sha256(data).hexdigest() != reference["manifest_sha256"]:
        raise ValueError("root control manifest changed")
    parsed: object = json.loads(data)
    if not isinstance(parsed, dict):
        raise ValueError("root control manifest is invalid")
    manifest = cast(dict[str, Any], parsed)
    if type(manifest.get("revision")) is not int or manifest.get("wave_id") != f"wave-{manifest['revision']}":
        raise ValueError("root control manifest has an invalid revision")
    if current_revision is not None and manifest["revision"] != current_revision:
        raise ValueError("root control result belongs to another wave")
    if any(
        manifest.get(key) != value
        for key, value in (
            ("session_id", state.get("session_id")),
            ("loop_id", state.get("loop_id")),
            ("wave_id", reference["wave_id"]),
            ("node_id", node_id),
        )
    ):
        raise ValueError("root control manifest belongs to another graph")
    source = manifest.get("result_file")
    if not isinstance(source, str) or _digest(Path(source)) != manifest.get("result_sha256"):
        raise ValueError("root control result file changed")
    if _result(json.loads(Path(source).read_text(encoding="utf-8"))) != manifest.get("result"):
        raise ValueError("root control result changed")
    return manifest


def load(path: Path, state: dict[str, Any], node_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return a staged result and reference, or None until the root acts."""
    active = _owned(state, node_id)
    target = _artifact(path, active["wave_id"], node_id)
    if not target.exists():
        return None
    reference = {
        "kind": "root_control",
        "wave_id": active["wave_id"],
        "node_id": node_id,
        "manifest_sha256": _digest(target),
    }
    manifest = validate(path, state, node_id, reference)
    return cast(dict[str, Any], manifest["result"]), reference
