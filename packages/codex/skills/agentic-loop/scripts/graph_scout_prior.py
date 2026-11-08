"""Authenticate complete prior scout refusals without changing ordinary audit evidence."""

from __future__ import annotations

from typing import Any, Optional, cast

import graph_contract
from graph_data import event_payload, object_value
from graph_identity import REFUSED_KEYS, REFUSED_OUTCOME, GraphError, is_contract_wave, task_name
from graph_transcript import error_shaped, launch_observations, native_dispatch_requests

Requests = dict[str, list[Optional[dict[str, Any]]]]


def verify_dispatch(
    state: dict[str, Any],
    node_id: str,
    attempt: int,
    wave_id: str,
    call_id: str,
    requests: Requests,
    strict: bool = False,
) -> dict[str, Any] | None:
    """Validate native dispatch evidence, preserving ordinary historical compatibility."""
    if not strict and not is_contract_wave(state, wave_id):
        return None
    calls = requests.get(call_id, [])
    if len(calls) != 1 or not isinstance(calls[0], dict):
        raise graph_contract.DispatchDeniedError("dispatch_missing_envelope", "native spawn has no unique request")
    request = calls[0]
    message = request.get("message")
    if not isinstance(message, str):
        raise graph_contract.DispatchDeniedError("dispatch_missing_envelope", "native spawn has no message")
    if request.get("task_name") != task_name(state["loop_id"], node_id, attempt):
        raise graph_contract.DispatchDeniedError("dispatch_foreign", "native spawn task name differs from its attempt")
    records = (
        object_value(value, "issued native dispatch") if strict else value
        for value in state["graph"].get("dispatches", {}).values()
    )
    issued = [
        record
        for record in records
        if record.get("node_id") == node_id and record.get("attempt") == attempt and record.get("wave_id") == wave_id
    ]
    if strict and len(issued) != 1:
        raise GraphError("prior refusal has no unique issued dispatch")
    if (
        len(issued) == 1
        and isinstance(issued[0].get("authorized"), dict)
        and "ciphertext_sha256" in issued[0]["authorized"]
    ):
        raise graph_contract.DispatchDeniedError(
            "dispatch_prompt_unverifiable", "encrypted native prompt has no verifiable instructions"
        )
    envelope = graph_contract.parse_envelope(message)
    record = graph_contract.check_ownership(state, envelope, live=False)
    waived = record.get("authorized") == {"tool_use_id": None, "mode": "off"}
    if not (waived or (not strict and graph_contract.dispatch_off())):
        record = graph_contract.check_dispatch(state, envelope, message, live=False)
    if (
        record.get("task_name") != request["task_name"]
        or record.get("attempt") != attempt
        or record["wave_id"] != wave_id
    ):
        raise graph_contract.DispatchDeniedError("dispatch_foreign", "native spawn does not own this graph attempt")
    if waived or (not strict and graph_contract.dispatch_off()):
        return record
    agent_type = request.get("agent_type", "")
    if not isinstance(agent_type, str):
        raise graph_contract.DispatchDeniedError("role_mismatch", "native spawn has an invalid agent type")
    graph_contract.assert_role(record["contract"], agent_type, "", None)
    allowed = ({"tool_use_id": call_id},) if strict else ({"tool_use_id": None}, {"tool_use_id": call_id})
    if record.get("authorized") not in allowed:
        raise graph_contract.DispatchDeniedError(
            "dispatch_unauthorized", "native spawn has no consumed dispatch authorization"
        )
    return record


def prove_prior_refusal(
    state: dict[str, Any],
    node_id: str,
    attempt: int,
    wave_id: str,
    cursor: int,
    records: list[tuple[int, dict[str, Any]]],
) -> int:
    """Return the unique failure-result line only after the entire prior proof agrees."""
    if node_id != "S2.5" or type(attempt) is not int or attempt < 2:
        raise GraphError("non-independent skip needs adjacent exact positive attempts")
    prior: list[dict[str, Any]] = []
    for value in cast(list[object], state["graph"]["nodes"][node_id]["evidence"]):
        if isinstance(value, dict):
            item = cast(dict[str, Any], value)
            if (
                item.get("kind") == "codex_agent"
                and item.get("outcome") == REFUSED_OUTCOME
                and item.get("attempt") == attempt - 1
            ):
                prior.append(item)
    if len(prior) != 1 or set(prior[0]) != REFUSED_KEYS or type(prior[0].get("attempt")) is not int:
        raise GraphError("non-independent skip needs one exact recorded scout spawn refusal")
    ref = prior[0]
    if not isinstance(ref.get("spawn_call_id"), str) or not ref["spawn_call_id"]:
        raise GraphError("prior refusal has no native call identity")
    observations = launch_observations(records).get(ref["spawn_call_id"])
    if (
        observations is None
        or len(observations["calls"]) != 1
        or len(observations["outputs"]) != 1
        or observations["activities"]
    ):
        raise GraphError("prior scout refusal needs one native call and one childless failure result")
    call_line = observations["calls"][0][0]
    result_line, output = observations["outputs"][0]
    if not error_shaped(event_payload(output).get("output")) or not call_line < result_line < cursor:
        raise GraphError("prior scout failure result is missing, successful or outside its earlier boundary")
    requests = native_dispatch_requests(records)
    issued = verify_dispatch(
        state, node_id, ref["attempt"], ref["wave_id"], ref["spawn_call_id"], requests, strict=True
    )
    if issued is None:
        raise GraphError("prior refusal has no safely bound issued dispatch")
    history = object_value(state["graph"].get("wave_history"), "native wave history")
    original = object_value(history.get(ref["wave_id"]), "prior refusal wave")
    current = object_value(history.get(wave_id), "current fallback wave")
    if (
        ref["wave_id"] == wave_id
        or type(original.get("cursor")) is not int
        or original["cursor"] < 1
        or call_line <= original["cursor"]
        or not isinstance(original.get("nodes"), list)
        or node_id not in original["nodes"]
        or type(original.get("revision")) is not int
        or type(issued.get("revision")) is not int
        or original["revision"] != issued["revision"]
        or type(current.get("revision")) is not int
        or original["revision"] >= current["revision"]
        or current.get("cursor") != cursor
    ):
        raise GraphError("prior refusal does not own an earlier original wave and cursor")
    return result_line
