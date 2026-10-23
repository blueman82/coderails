"""Issue one complete driver wave from the shared graph and dispatch contracts."""

from __future__ import annotations

import copy
import hashlib
import re
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
    if control:
        raise ValueError(f"root-owned nodes cannot receive driver worker dispatch: {', '.join(sorted(control))}")
    base = graph_contract.base_ref()
    dispatches: list[dict[str, Any]] = []
    for node_id in active["nodes"]:
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
    return {"state": proposed, "wave": active, "dispatches": dispatches}


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
