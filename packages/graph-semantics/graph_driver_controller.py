"""Run one bounded driver observation through provider graph commands."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, cast

import graph_contract
import graph_driver_evidence
import graph_driver_process
import graph_semantics
from graph_vocab import decision_pending

Command = Callable[[Path], list[str]]
Result = Callable[[Path, int], dict[str, Any]]


def _graph(script: Path, name: str, path: Path, *args: str) -> dict[str, Any]:
    """Call the provider's public, locked graph command and read one JSON report."""
    run = subprocess.run(
        [sys.executable, str(script), name, str(path), *args], capture_output=True, text=True, check=False
    )
    if run.returncode:
        raise ValueError(f"{name} refused: {run.stderr.strip()}")
    report = json.loads(run.stdout)
    if not isinstance(report, dict):
        raise ValueError(f"{name} returned no object")
    return cast(dict[str, Any], report)


def _load(path: Path, session: str) -> dict[str, Any]:
    """Check graph ownership and revalidate retained evidence before work."""
    state = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    graph_semantics.validate(state)
    if state["session_id"] != session or state["graph"].get("dispatch_mode") != "driver":
        raise ValueError("driver graph belongs to another session or mode")
    graph_driver_evidence.validate_backup(path, state)
    graph_driver_evidence.validate_history(path, state)
    return state


def _dispatches(state: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Require exactly one driver record for every node in the active wave."""
    active_value: object = state["graph"]["active_wave"]
    if not isinstance(active_value, dict):
        raise ValueError("driver graph has no active wave")
    active = cast(dict[str, Any], active_value)
    records = [
        (identifier, cast(dict[str, Any], record))
        for identifier, record in state["graph"]["dispatches"].items()
        if record.get("wave_id") == active["wave_id"]
    ]
    nodes = [record["node_id"] for _, record in records]
    if (
        len(nodes) != len(active["nodes"])
        or set(nodes) != set(active["nodes"])
        or any(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", identifier) is None for identifier, _ in records)
    ):
        raise ValueError("driver wave lacks an exact dispatch for each node")
    return sorted(records, key=lambda item: item[1]["node_id"])


def _prompt(path: Path, state: dict[str, Any], identifier: str, record: dict[str, Any]) -> Path:
    """Write the exact envelope and contract once before authorization."""
    artifact = path.parent / "driver-evidence" / identifier
    if artifact.parent.is_symlink() or artifact.is_symlink():
        raise ValueError("driver artifact path is a symlink")
    artifact.mkdir(parents=True, exist_ok=True)
    prompt = artifact / "prompt.txt"
    content = graph_contract.prompt_prefix(state, identifier, record) + "\n"
    content += graph_contract.render_sections(record["contract"]) + "\n"
    if prompt.exists():
        if prompt.read_text(encoding="utf-8") != content:
            raise ValueError("existing driver prompt differs from its contract")
    else:
        with prompt.open("x", encoding="utf-8") as stream:
            stream.write(content)
    return prompt


def _reference(
    path: Path, state: dict[str, Any], node_id: str, identifier: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rebuild and validate a reference after a controller restart."""
    record = state["graph"]["dispatches"][identifier]
    manifest_path = path.parent / "driver-evidence" / identifier / "manifest.json"
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    reference = {
        "kind": "driver_worker",
        "dispatch_id": identifier,
        "wave_id": record["wave_id"],
        "attempt": record["attempt"],
        "manifest_sha256": digest,
    }
    manifest = graph_driver_evidence.validate(path, state, node_id, reference)
    return reference, manifest


def drive_once(
    path: Path,
    session: str,
    script: Path,
    checkout: Path,
    provider: str,
    command: Command,
    result: Result,
) -> dict[str, Any]:
    """Start or observe each worker once, then atomically record a full wave."""
    with graph_driver_process.lease(path):
        state = _load(path, session)
        if state["graph"]["active_wave"] is None:
            if state["graph"]["hard_stop"] is not None:
                return {"status": "stopped", "reason": "hard_stop"}
            if any(decision_pending(state, node_id) for node_id in state["graph"]["nodes"]):
                return {"status": "paused", "reason": "decision_pending"}
            if not graph_semantics.ready(state):
                return {"status": "paused", "reason": "no_ready_nodes"}
            _graph(script, "begin-driver-wave", path)
            state = _load(path, session)
        active = cast(dict[str, Any], state["graph"]["active_wave"])
        results: dict[str, Any] = {}
        references: dict[str, Any] = {}
        for identifier, record in _dispatches(state):
            node_id = record["node_id"]
            prompt = _prompt(path, state, identifier, record)
            artifact = prompt.parent
            newly_authorized = record.get("authorized") is None
            if newly_authorized:
                _graph(
                    script,
                    "authorize-driver",
                    path,
                    "--session",
                    session,
                    "--dispatch-id",
                    identifier,
                    "--prompt-file",
                    str(prompt),
                    "--role",
                    record["contract"]["role"],
                    "--driver-run-id",
                    secrets.token_hex(16),
                )
                state = _load(path, session)
            if (artifact / "manifest.json").exists():
                reference, manifest = _reference(path, state, node_id, identifier)
            else:
                if not (artifact / "launch.json").exists():
                    if not newly_authorized:
                        return {"status": "unresolved", "reason": "authorized_without_launch", "node": node_id}
                    graph_driver_process.start(artifact, command(prompt), checkout)
                observation = graph_driver_process.observe(artifact, 0.05)
                if observation["status"] != "finished":
                    return {"status": observation["status"], "node": node_id}
                parsed = result(artifact / "output.jsonl", observation["exit_code"])
                reference = graph_driver_evidence.seal(
                    path, state, node_id, identifier, checkout, provider, observation["exit_code"], parsed
                )
                manifest = graph_driver_evidence.validate(path, state, node_id, reference)
            results[node_id] = manifest["result"]
            references[node_id] = reference
        _graph(
            script,
            "record-driver-wave",
            path,
            json.dumps({"wave_id": active["wave_id"], "results": results, "references": references}),
        )
        return {"status": "recorded", "wave_id": active["wave_id"], "nodes": sorted(results)}
