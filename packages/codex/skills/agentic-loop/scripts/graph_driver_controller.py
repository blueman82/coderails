"""Run one bounded driver observation through provider graph commands."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional, Union, cast

import graph_contract
import graph_driver_control
import graph_driver_evidence
import graph_driver_process
import graph_semantics
import graph_spec
from graph_vocab import decision_pending

Command = Callable[[Path, dict[str, Any]], tuple[list[str], Optional[dict[str, str]], Optional[Path]]]
Result = Callable[[Path, int], dict[str, Any]]
Checkouts = Union[Path, dict[str, Path]]


def assign_scope(state: dict[str, Any], session: str, unit: str, scope: str) -> dict[str, Any]:
    """Bind an existing pending unit to a task before its next wave."""
    raw_units: object = state.get("work_units")
    units = cast(dict[str, object], raw_units) if isinstance(raw_units, dict) else {}
    record = units.get(unit)
    if state.get("session_id") != session or state.get("status") != "in-progress":
        raise ValueError("unit scope belongs to another or inactive session")
    graph = cast(dict[str, object], state["graph"])
    if graph.get("active_wave") is not None:
        raise ValueError("unit scope requires no active wave")
    if not scope.strip() or not isinstance(record, dict) or cast(dict[str, object], record).get("status") != "pending":
        raise ValueError("unit scope requires a pending unit and nonblank task")
    if cast(dict[str, object], record).get("scope"):
        raise ValueError("unit scope is already assigned")
    proposed = copy.deepcopy(state)
    proposed["work_units"][unit]["scope"] = scope.strip()
    proposed["revision"] += 1
    graph_semantics.validate(proposed)
    return proposed


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
    workers = set(active["nodes"]) - set(_control_nodes(active["nodes"]))
    if (
        len(nodes) != len(workers)
        or set(nodes) != workers
        or any(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", identifier) is None for identifier, _ in records)
    ):
        raise ValueError("driver wave lacks an exact dispatch for each node")
    return sorted(records, key=lambda item: item[1]["node_id"])


def _control_nodes(nodes: list[str]) -> list[str]:
    """Keep root-owned graph steps out of external worker processes."""
    spec = graph_spec.load_spec()
    return sorted(node_id for node_id in nodes if (graph_spec.node_for(spec, node_id) or {}).get("agent_role") is None)


def _missing_tasks(state: dict[str, Any], nodes: list[str]) -> list[str]:
    """Refuse implementation workers without an actual unit assignment."""
    units = state.get("work_units", {})
    return sorted(
        node_id
        for node_id in nodes
        if graph_spec.split_id(node_id)[0] == "U3"
        and not str(units.get(graph_spec.split_id(node_id)[1], {}).get("scope", "")).strip()
    )


def parse_checkout_map(path: Path) -> dict[str, Path]:
    """Read one explicit node-to-checkout map for a foreground wave."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("checkout map is missing or a symlink")
    parsed: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or not parsed:
        raise ValueError("checkout map must bind node ids to absolute paths")
    entries = cast(dict[object, object], parsed)
    if not all(
        isinstance(key, str) and isinstance(value, str) and Path(value).is_absolute() for key, value in entries.items()
    ):
        raise ValueError("checkout map must bind node ids to absolute paths")
    return {key: Path(value) for key, value in cast(dict[str, str], entries).items()}


def select_checkouts(checkout: Path | None, map_path: Path | None) -> Checkouts:
    """Choose the single or mapped checkout form exposed by the CLI."""
    if map_path is not None:
        return parse_checkout_map(map_path)
    if checkout is not None:
        return checkout
    return {}


def checkout_for(checkouts: Checkouts, node_id: str) -> Path:
    """Select one existing, real checkout for an issued node."""
    path = checkouts[node_id] if isinstance(checkouts, dict) else checkouts
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"worker checkout is missing or a symlink: {node_id}")
    return path.resolve(strict=True)


def _checkout_problem(state: dict[str, Any], nodes: list[str], checkouts: Checkouts, path: Path) -> str | None:
    """Keep each worker attempt on its own retained checkout."""
    if not nodes:
        return None
    if isinstance(checkouts, dict):
        if set(checkouts) != set(nodes):
            return "checkout_map_mismatch"
    elif len(nodes) != 1:
        return "checkout_map_required"
    paths = [checkout_for(checkouts, node_id) for node_id in nodes]
    if len(set(paths)) != len(paths):
        return "checkout_reused_in_wave"
    nodes_data = cast(dict[str, dict[str, Any]], state["graph"]["nodes"])
    for node_id, node in nodes_data.items():
        for item in cast(list[Any], node["evidence"]):
            if isinstance(item, dict):
                reference = cast(dict[str, Any], item)
                if reference.get("kind") == "driver_worker":
                    manifest = graph_driver_evidence.validate(path, state, node_id, reference)
                    if Path(manifest["checkout"]) in paths:
                        return "checkout_already_used"
    return None


def _prompt(
    path: Path,
    state: dict[str, Any],
    identifier: str,
    record: dict[str, Any],
    checkout: Path,
    provider: str,
    script: Path,
) -> Path:
    """Write the exact envelope and contract once before authorization."""
    artifact = path.parent / "driver-evidence" / identifier
    if artifact.parent.is_symlink() or artifact.is_symlink():
        raise ValueError("driver artifact path is a symlink")
    artifact.mkdir(parents=True, exist_ok=True)
    prompt = artifact / "prompt.txt"
    content = graph_contract.prompt_prefix(state, identifier, record) + "\n"
    content += graph_contract.render_sections(record["contract"]) + "\n"
    node = graph_spec.node_for(graph_spec.load_spec(), record["node_id"])
    if node is None:
        raise ValueError("driver task has no graph specification")
    role = record["contract"]["role"]
    if role not in graph_contract.roles():
        raise ValueError("driver task has no valid role")
    suffix = ".toml" if provider == "codex" else ".md"
    source = script.resolve().parents[3] / "agents" / f"{role}{suffix}"
    if source.is_symlink() or not source.is_file():
        raise ValueError("driver role instructions are missing")
    content += f"\nRole instructions for {role}:\n{source.read_text(encoding='utf-8')}\n"
    content += f"\nTask: {node['label']}\n"
    implementation = graph_spec.split_id(record["node_id"])[0] == "U3"
    wiki = record["node_id"] == "S9-wiki"
    acceptance = (
        "wiki edits and lint ready for root publication"
        if wiki
        else ("source edits and checks ready for root publication" if implementation else node["ready_when"])
    )
    content += f"Acceptance: {acceptance}\n"
    content += f"Assigned scope: {record['contract']['scope']}\n"
    content += f"Checkout: {checkout}\n"
    content += "Work only in the assigned checkout. Report failed if the task is unclear or incomplete.\n"
    content += "For done, give a final_report with cited claims and explicit did_not_verify items.\n"
    if implementation or wiki:
        content += "Do not run git add or git commit. The root will commit and open the PR after checking your work.\n"
    if wiki:
        content += "The root will merge the wiki PR and verify its commit on origin/main before recording done.\n"
    content += "Do not push, open a PR, merge, or change progress.json without the owner's explicit go.\n"
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


def _publication_pause(checkout: Path, node_id: str, result: dict[str, Any]) -> dict[str, Any] | None:
    """Leave a successful source worker open until root publication."""
    if graph_driver_evidence.needs_publication(node_id, result):
        try:
            graph_driver_evidence.publication(checkout, require_merged=node_id == "S9-wiki")
        except ValueError as error:
            return {"status": "paused", "reason": "publication_required", "node": node_id, "detail": str(error)}
    return None


def drive_once(
    path: Path,
    session: str,
    script: Path,
    checkout: Checkouts,
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
            ready = graph_semantics.ready(state)
            workers = sorted(set(ready) - set(_control_nodes(ready)))
            missing = _missing_tasks(state, workers)
            if missing:
                return {"status": "paused", "reason": "missing_task", "nodes": missing}
            if not ready:
                return {"status": "paused", "reason": "no_ready_nodes"}
            problem = _checkout_problem(state, workers, checkout, path)
            if problem:
                return {"status": "paused", "reason": problem, "nodes": ready}
            _graph(script, "begin-driver-wave", path)
            state = _load(path, session)
        active = cast(dict[str, Any], state["graph"]["active_wave"])
        workers = sorted(set(active["nodes"]) - set(_control_nodes(active["nodes"])))
        if _missing_tasks(state, workers):
            return {"status": "unresolved", "reason": "active_missing_task", "nodes": workers}
        problem = _checkout_problem(state, workers, checkout, path)
        if problem:
            return {"status": "unresolved", "reason": problem, "nodes": workers}
        results: dict[str, Any] = {}
        references: dict[str, Any] = {}
        missing_controls: list[str] = []
        for node_id in _control_nodes(active["nodes"]):
            staged = graph_driver_control.load(path, state, node_id)
            if staged is None:
                missing_controls.append(node_id)
            else:
                results[node_id], references[node_id] = staged
        if missing_controls:
            return {"status": "paused", "reason": "control_node", "nodes": missing_controls}
        for identifier, record in _dispatches(state):
            node_id = record["node_id"]
            worker_checkout = checkout_for(checkout, node_id)
            prompt = _prompt(path, state, identifier, record, worker_checkout, provider, script)
            prepared = command(prompt, record) if record.get("authorized") is None else None
            if prepared is not None:
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
            if (prompt.parent / "manifest.json").exists():
                reference, manifest = _reference(path, state, node_id, identifier)
            else:
                if not (prompt.parent / "launch.json").exists():
                    if prepared is None:
                        prepared = command(prompt, record)
                    argv, environment, input_path = prepared
                    graph_driver_process.start(
                        prompt.parent, argv, worker_checkout, environment=environment, stdin_path=input_path
                    )
                observation = graph_driver_process.observe(prompt.parent, 0.05)
                if observation["status"] != "finished":
                    return {"status": observation["status"], "node": node_id}
                parsed = result(prompt.parent / "output.jsonl", observation["exit_code"])
                if pause := _publication_pause(worker_checkout, node_id, parsed):
                    return pause
                reference = graph_driver_evidence.seal(
                    path, state, node_id, identifier, worker_checkout, provider, observation["exit_code"], parsed
                )
                manifest = graph_driver_evidence.validate(path, state, node_id, reference)
            if Path(manifest["checkout"]) != worker_checkout:
                return {"status": "unresolved", "reason": "checkout_changed", "node": node_id}
            results[node_id] = manifest["result"]
            references[node_id] = reference
        _graph(
            script,
            "record-driver-wave",
            path,
            json.dumps({"wave_id": active["wave_id"], "results": results, "references": references}),
        )
        return {"status": "recorded", "wave_id": active["wave_id"], "nodes": sorted(results)}


def drive_wave(
    path: Path,
    session: str,
    script: Path,
    checkout: Checkouts,
    provider: str,
    command: Command,
    result: Result,
) -> dict[str, Any]:
    """Hold one foreground lease until the current complete wave is recorded or paused."""
    with graph_driver_process.lease(path, ".controller.lock"):
        while True:
            report = drive_once(path, session, script, checkout, provider, command, result)
            if report["status"] != "running":
                return report
            time.sleep(0.5)
