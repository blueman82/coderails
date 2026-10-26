"""Codex wave dispatch: begin a wave, bind and record its results, and authorize a worker spawn."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from pathlib import Path
from typing import Any, cast

import graph_contract
import graph_repair
import graph_semantics
import graph_stops
import worker_status
from graph_evidence import bind_worker_evidence, validate_evals
from graph_identity import GraphError, classify_worker_evidence, new_evidence_writes_enabled, next_attempt, task_name
from graph_io import load as _load
from graph_io import locked as _locked
from graph_io import object_value as _object
from graph_io import write as _write
from graph_recovery import RecoveryRefusedError, trace, traced_refusal
from graph_transcript import transcript_cursor
from json_types import JsonValue


def _opaque_ciphertext(message: str) -> bool:
    """Recognize only the observed single-line Fernet wire shape; do not claim to decrypt it."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", message):
        return False
    try:
        raw = base64.b64decode(message, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error):
        return False
    return len(raw) >= 73 and raw[0] == 0x80 and (len(raw) - 57) % 16 == 0


def _opaque_request(state: dict[str, Any], task: str, dispatch_id: str, tool_use_id: str) -> dict[str, Any]:
    """Resolve one clear native task to its already issued dispatch without reading opaque prompt text."""
    if not tool_use_id or not re.fullmatch(r"[A-Za-z0-9_-]+", tool_use_id):
        raise graph_contract.DispatchDeniedError("dispatch_call_id_missing", "opaque spawn needs a native call id")
    matches = [(key, value) for key, value in state["graph"]["dispatches"].items() if value.get("task_name") == task]
    if len(matches) != 1:
        raise graph_contract.DispatchDeniedError("dispatch_foreign", "task name must resolve one dispatch")
    found_id, record = matches[0]
    if dispatch_id and dispatch_id != found_id:
        raise graph_contract.DispatchDeniedError("dispatch_unknown_id", "dispatch id differs from task")
    return {
        "dispatch_id": found_id,
        "session_id": state["session_id"],
        "loop_id": state["loop_id"],
        "revision": record["revision"],
        "wave_id": record["wave_id"],
        "node_id": record["node_id"],
    }


def _check_opaque_contract(state: dict[str, Any], record: dict[str, Any], task: str) -> None:
    """Check the stored contract and canonical attempt when the prompt body cannot be read."""
    try:
        contract = graph_contract.validate_contract(record.get("contract"))
    except (ValueError, TypeError) as error:
        raise graph_contract.DispatchDeniedError("dispatch_contract_altered", str(error)) from error
    if (
        record.get("envelope_version") != graph_contract.ENVELOPE_VERSION
        or graph_contract.sections_sha256(contract) != record.get("prompt_sections_sha256")
        or task != task_name(state["loop_id"], record["node_id"], record["attempt"])
    ):
        raise graph_contract.DispatchDeniedError("dispatch_contract_altered", "stored native contract differs")


def begin_wave(path: Path) -> dict[str, Any]:
    """Start one core wave under the native state lock and frozen eval gate; store one dispatch record per node."""
    base = graph_contract.base_ref()
    with _locked(path):
        state = _load(path)
        try:
            graph_contract.require_converted(state)
        except graph_contract.DispatchDeniedError as error:
            raise GraphError(str(error)) from error
        validate_evals(state, None, path.with_name("evals.json"))
        transition = graph_semantics.begin_wave(state)
        proposed = cast(dict[str, Any], transition["state"])
        wave = cast(dict[str, Any], transition["wave"])
        proposed["graph"]["active_wave"]["transcript_cursor"] = transcript_cursor(proposed["session_id"])
        task_names = {
            node_id: task_name(proposed["loop_id"], node_id, next_attempt(proposed["graph"]["nodes"][node_id]))
            for node_id in wave["nodes"]
        }
        dispatches: list[dict[str, Any]] = []
        for node_id in wave["nodes"]:
            contract = graph_contract.build_contract(
                proposed, node_id, base, path, Path(__file__).resolve().parents[3] / "scripts/push.py"
            )
            mode = "native" if contract["role"] == "loop-worker" else None
            attempt = next_attempt(proposed["graph"]["nodes"][node_id])
            identifier, record = graph_contract.make_record(proposed, node_id, wave["wave_id"], attempt, contract, mode)
            record["task_name"] = task_names[node_id]
            proposed["graph"].setdefault("dispatches", {})[identifier] = record
            dispatches.append(
                {
                    "node_id": node_id,
                    "dispatch_id": identifier,
                    "task_name": task_names[node_id],
                    "prompt_prefix": graph_contract.prompt_prefix(proposed, identifier, record),
                    "prompt_sections": graph_contract.render_sections(contract),
                }
            )
        graph_semantics.validate(proposed)
        _write(path, proposed)
        return {
            "wave_id": wave["wave_id"],
            "nodes": wave["nodes"],
            "node_names": graph_semantics.node_names(proposed["graph"]["nodes"]),
            "task_names": task_names,
            "revision": proposed["revision"],
            "dispatches": dispatches,
        }


def apply_record(state: dict[str, Any], raw_results: str, typed: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind native evidence and compute the post-record state for exactly the active wave; writes nothing.

    `typed` (record-wave only) first runs worker_status.prepare: typed worker statuses and final reports are validated,
    statuses become core `failed` results, and the extracted rows ride back in the returned transition.
    """
    try:
        parsed_results: JsonValue = cast(JsonValue, json.loads(raw_results))
    except json.JSONDecodeError as error:
        raise GraphError(f"results are not valid JSON: {error}") from error
    graph = state["graph"]
    if graph["active_wave"] is None:
        raise GraphError("no active wave exists")
    active = cast(dict[str, Any], graph["active_wave"])
    envelope = _object(cast(object, parsed_results), "results")
    if set(envelope) != {"wave_id", "results"}:
        raise GraphError("results must contain exactly wave_id and results")
    results = _object(envelope.get("results"), "results.results")
    statuses: list[dict[str, Any]] = []
    reports: dict[str, Any] = {}
    if typed:
        try:
            results, statuses, reports = worker_status.prepare(state, results)
        except worker_status.WorkerResultError as error:
            nodes = (error.node,) if error.node else ()
            raise RecoveryRefusedError(error.code, error.message, nodes) from error
    transition = graph_semantics.record_wave(state, envelope.get("wave_id"), results)
    proposed = cast(dict[str, Any], transition["state"])
    worker_status.retain_decision_slot(proposed, statuses)
    status_nodes = {status["node"] for status in statuses}
    graph_repair.apply_failed_gates(
        transition, {node: result for node, result in results.items() if node not in status_nodes}
    )
    stale_nodes = frozenset(node for node, result in results.items() if result["outcome"] == "stale")
    failed_nodes = frozenset(node for node, result in results.items() if result["outcome"] == "failed")
    references, identifiers = bind_worker_evidence(state, active, stale_nodes, failed_nodes)
    if any(
        classify_worker_evidence(cast(dict[str, Any], result).get("evidence"), identifiers)[0]
        for result in results.values()
        if isinstance(result, dict)
    ):
        raise GraphError("result evidence must not contain worker evidence")
    for node_id, reference in references.items():
        proposed["graph"]["nodes"][node_id]["evidence"].append(reference)
    worker_status.record_into(proposed, active["wave_id"], statuses, reports)
    return proposed, {**transition, "statuses": statuses, "reports": reports}


def record_wave(path: Path, raw_results: str) -> dict[str, Any]:
    """Bind native evidence and atomically record exactly the active wave, typed worker results included."""
    with _locked(path):
        state = _load(path)
        with traced_refusal(path, state, "record-wave"):
            proposed, transition = apply_record(state, raw_results, typed=True)
        statuses = transition["statuses"]
        if statuses:  # one typed stop row on the post-record state, in the same locked write
            category, code, reason = worker_status.stop_for(statuses)
            proposed = graph_stops.record_stop(proposed, state["session_id"], category, code, reason)["state"]
        graph_semantics.validate(proposed)
        _write(path, proposed)
        for item in [*statuses, *({"node": node, "status": "FINAL_REPORT"} for node in transition["reports"])]:
            name = "final_report_recorded" if item["status"] == "FINAL_REPORT" else f"worker_status_{item['status']}"
            trace(path, proposed, "recorded", name.lower(), {}, [(item["node"], None, None)], "record-wave")
        return {
            "revision": proposed["revision"],
            "released_joins": transition["released_joins"],
            "ready": graph_semantics.ready(proposed),
        }


def authorize_dispatch(
    path: Path,
    session: str,
    dispatch_id: str,
    message_file: Path,
    agent_type: str,
    task: str,
    evals_path: Path,
    tool_use_id: str = "",
) -> dict[str, Any]:
    """Authorize one native spawn under the graph lock; refusal leaves state unchanged and writes a coded trace."""
    with _locked(path):
        state = _load(path)
        if state["session_id"] != session:
            raise GraphError("session does not own this loop")
        if state["status"] == "complete":
            raise GraphError("completed graph does not own worker dispatch")
        named: str | None = None
        inputs = {"session": session, "role": agent_type}
        if graph_contract.dispatch_off():
            try:
                graph_contract.require_converted(state)
                message = message_file.read_text(encoding="utf-8")
                request = graph_contract.parse_envelope(message)
                if request["dispatch_id"] != dispatch_id:
                    raise graph_contract.DispatchDeniedError(
                        "dispatch_unknown_id", "--dispatch-id is not the envelope's"
                    )
                record = graph_contract.check_ownership(state, request, live=True)
                graph_contract.require_publication(
                    record, path, Path(__file__).resolve().parents[3] / "scripts/push.py"
                )
                if record.get("task_name") != task:
                    raise graph_contract.DispatchDeniedError(
                        "dispatch_foreign", "task_name is not the record's task name"
                    )
                validate_evals(state, None, evals_path)
            except graph_contract.DispatchDeniedError as error:
                trace(path, state, "refused", error.code, inputs, [(None, None, None)], "authorize-dispatch")
                raise GraphError(str(error)) from error
            except OSError as error:
                raise GraphError(f"cannot read the message file: {error}") from error
            if record["authorized"] is None and new_evidence_writes_enabled():
                record["authorized"] = {"tool_use_id": None, "mode": "off"}
                _write(path, state)
            trace(
                path,
                state,
                "reported",
                "dispatch_check_off",
                inputs,
                [(request["node_id"], None, None)],
                "authorize-dispatch",
            )
            return {"loop_id": state["loop_id"], "task_name": task, "dispatch_id": dispatch_id, "off": True}
        try:
            graph_contract.require_converted(state)
            message = message_file.read_text(encoding="utf-8")
            opaque = _opaque_ciphertext(message)
            request = (
                _opaque_request(state, task, dispatch_id, tool_use_id)
                if opaque
                else graph_contract.parse_envelope(message)
            )
            named = request["node_id"]
            if not opaque and request["dispatch_id"] != dispatch_id:
                raise graph_contract.DispatchDeniedError("dispatch_unknown_id", "--dispatch-id is not the envelope's")
            if opaque:
                record = graph_contract.check_ownership(state, request, live=True)
            else:
                record = graph_contract.check_dispatch(state, request, message, live=True)
            if opaque:
                _check_opaque_contract(state, record, task)
            graph_contract.require_publication(record, path, Path(__file__).resolve().parents[3] / "scripts/push.py")
            if record.get("task_name") != task:
                raise graph_contract.DispatchDeniedError("dispatch_foreign", "task_name is not the record's task name")
            graph_contract.assert_role(record["contract"], agent_type, "", None)
            validate_evals(state, None, evals_path)
            if record["authorized"] is not None:
                raise graph_contract.DispatchDeniedError("dispatch_replayed", "dispatch envelope was already used")
        except graph_contract.DispatchDeniedError as error:
            trace(path, state, "refused", error.code, inputs, [(named, None, None)], "authorize-dispatch")
            raise GraphError(str(error)) from error
        except OSError as error:
            raise GraphError(f"cannot read the message file: {error}") from error
        record["authorized"] = (
            {"tool_use_id": tool_use_id, "ciphertext_sha256": hashlib.sha256(message.encode()).hexdigest()}
            if opaque
            else {"tool_use_id": (tool_use_id or None) if new_evidence_writes_enabled() else None}
        )
        _write(path, state)
        trace(path, state, "authorized", "dispatch_authorized", inputs, [(named, None, None)], "authorize-dispatch")
        return {
            "loop_id": state["loop_id"],
            "node": request["node_id"],
            "task_name": task,
            "wave_id": record["wave_id"],
            "revision": state["revision"],
            "dispatch_id": request["dispatch_id"],
        }
