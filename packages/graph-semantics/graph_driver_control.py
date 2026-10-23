"""Bind root-owned graph results to durable files without dispatching a worker."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import graph_spec

_MAX_RESULT_BYTES = 1_000_000


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
    active = graph.get("active_wave")
    if isinstance(active, dict) and (
        reference["wave_id"] != cast(dict[str, Any], active).get("wave_id")
        or node_id not in cast(dict[str, Any], active).get("nodes", [])
    ):
        raise ValueError("root control result belongs to another wave")
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
    if isinstance(active, dict) and manifest["revision"] != cast(dict[str, Any], active).get("revision"):
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
