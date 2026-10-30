"""Issue one complete driver wave from the shared graph and dispatch contracts."""

from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import graph_contract
import graph_semantics
import graph_spec


def begin_wave(state: dict[str, Any], progress: Path, push_script: Path) -> dict[str, Any]:
    """Prepare all ready nodes and one unconsumed driver record for each."""
    if state["graph"].get("dispatch_mode") != "driver":
        raise ValueError("begin-driver-wave requires a cutover graph")
    graph_contract.require_converted(state)
    transition = graph_semantics.begin_wave(state)
    proposed = cast(dict[str, Any], transition["state"])
    active = cast(dict[str, Any], proposed["graph"]["active_wave"])
    spec = graph_spec.load_spec()
    control = [
        node_id for node_id in active["nodes"] if (graph_spec.node_for(spec, node_id) or {}).get("agent_role") is None
    ]
    base = graph_contract.base_ref()
    dispatches: list[dict[str, Any]] = []
    for node_id in active["nodes"]:
        if node_id in control:
            continue
        node = proposed["graph"]["nodes"][node_id]
        attempt = node["retry"]["attempts"] + node["respawn"]["generation"] + 1
        contract = graph_contract.build_contract(proposed, node_id, base, progress, push_script)
        dispatch_id, record = graph_contract.make_record(
            proposed, node_id, active["wave_id"], attempt, contract, "driver"
        )
        record["task_name"] = "driver_" + dispatch_id
        proposed["graph"].setdefault("dispatches", {})[dispatch_id] = record
        dispatches.append(
            {
                "node_id": node_id,
                "dispatch_id": dispatch_id,
                "task_name": record["task_name"],
                "prompt_prefix": graph_contract.prompt_prefix(proposed, dispatch_id, record),
                "prompt_sections": graph_contract.render_sections(contract),
            }
        )
    graph_semantics.validate(proposed)
    return {"state": proposed, "wave": active, "dispatches": dispatches, "control_nodes": sorted(control)}


def authorize(
    state: dict[str, Any],
    progress: Path,
    push_script: Path,
    session: str,
    dispatch_id: str,
    prompt_file: Path,
    role: str,
    driver_run_id: str,
) -> dict[str, Any]:
    """Consume one exact driver dispatch slot before the worker process starts."""
    if state["graph"].get("dispatch_mode") != "driver" or state["session_id"] != session:
        raise ValueError("driver dispatch belongs to another mode or session")
    if re.fullmatch(r"[A-Za-z0-9_-]{1,100}", driver_run_id) is None:
        raise ValueError("driver run id is invalid")
    expected = progress.parent / "driver-evidence" / dispatch_id / "prompt.txt"
    if prompt_file != expected or prompt_file.is_symlink() or not prompt_file.is_file():
        raise ValueError("driver prompt file is not the owned artifact")
    prompt_bytes = prompt_file.read_bytes()
    prompt = prompt_bytes.decode("utf-8")
    envelope = graph_contract.parse_envelope(prompt)
    if envelope["dispatch_id"] != dispatch_id:
        raise ValueError("driver prompt names another dispatch")
    record = graph_contract.check_dispatch(state, envelope, prompt, live=True)
    graph_contract.require_publication(record, progress, push_script)
    if record.get("dispatch_mode") != "driver" or record.get("authorized") is not None:
        raise ValueError("driver dispatch mode is wrong or already authorized")
    if role != record["contract"]["role"]:
        raise ValueError("driver role does not match its contract")
    if any(
        isinstance(item.get("authorized"), dict) and item["authorized"].get("driver_run_id") == driver_run_id
        for item in state["graph"].get("dispatches", {}).values()
    ):
        raise ValueError("driver run id was already used")
    proposed = copy.deepcopy(state)
    proposed["graph"]["dispatches"][dispatch_id]["authorized"] = {
        "driver_run_id": driver_run_id,
        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
    }
    return proposed


def write_prompt(
    path: Path,
    state: dict[str, Any],
    identifier: str,
    record: dict[str, Any],
    checkout: Path,
    provider: str,
    script: Path,
    *,
    publication_checkout: Path | None = None,
    workspace_sha256: str | None = None,
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
    if publication_checkout is not None:
        content += f"Root publication checkout: {publication_checkout} (worker writes forbidden)\n"
        content += f"Workspace SHA256: {workspace_sha256}\n"
    content += "Work only in the assigned checkout. Report failed if the task is unclear or incomplete.\n"
    content += "For done, give a final_report with cited claims and explicit did_not_verify items.\n"
    content += (
        "For a human request, set outcome to NEEDS_DECISION, OUTSIDE_SCOPE, or IRREVERSIBLE_ACTION. "
        "Put the matching typed worker status object as JSON in evidence and set final_report null.\n"
    )
    if implementation or wiki:
        content += "Do not run git add or git commit. The root will commit and open the PR after checking your work.\n"
    if wiki:
        content += "If no wiki update is in scope, report skipped with final_report null.\n"
        content += "The root will merge the wiki PR and verify its commit on origin/main before recording done.\n"
    content += "Do not push, open a PR, merge, or change progress.json without the owner's explicit go.\n"
    if prompt.exists():
        if prompt.read_text(encoding="utf-8") != content:
            raise ValueError("existing driver prompt differs from its contract")
    else:
        with prompt.open("x", encoding="utf-8") as stream:
            stream.write(content)
    return prompt


Prepare = Callable[[Path, dict[str, Any], str, dict[str, Any], Path], dict[str, Any]]


def prepare_prompt(
    path: Path,
    state: dict[str, Any],
    identifier: str,
    record: dict[str, Any],
    checkout: Path,
    provider: str,
    script: Path,
    prepare: Prepare | None,
) -> Path:
    """Prepare an optional contained workspace before rendering and authorizing its path."""
    artifact = path.parent / "driver-evidence" / identifier
    if artifact.parent.is_symlink() or artifact.is_symlink():
        raise ValueError("driver artifact path is a symlink")
    if (artifact / "manifest.json").exists():
        return artifact / "prompt.txt"
    workspace = prepare(path, state, identifier, record, checkout) if prepare is not None else None
    execution = Path(workspace["execution"]) if workspace else checkout
    extra: dict[str, Any] = {}
    if workspace:
        extra = {
            "publication_checkout": checkout,
            "workspace_sha256": hashlib.sha256((artifact / "workspace.json").read_bytes()).hexdigest(),
        }
    return write_prompt(path, state, identifier, record, execution, provider, script, **extra)
