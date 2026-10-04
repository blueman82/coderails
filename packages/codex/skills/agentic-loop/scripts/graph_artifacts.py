"""Validate native graph eval, proof, and retrospective artifacts."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, cast

from graph_data import array_value, event_payload, load_evidence, nonempty, object_value, read_records
from graph_identity import GraphError, is_frozen_loop_evals
from json_types import JsonValue

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib.eval_integrity import IntegrityError, verify_suite  # noqa: E402


def _matching(evidence: dict[str, Any], state: dict[str, Any], label: str) -> None:
    if evidence.get("session_id") != state["session_id"] or evidence.get("loop_id") != state["loop_id"]:
        raise GraphError(f"{label} belongs to a different loop")


def _grading_checksum(evals: dict[str, Any], result: str) -> str:
    raw_evals = array_value(evals.get("evals"), "evals.evals")
    canonical: list[dict[str, Any]] = []
    for index, raw_eval in enumerate(raw_evals):
        item = object_value(raw_eval, f"evals.evals[{index}]")
        canonical.append({key: item.get(key) for key in ("id", "priority", "status")})
    encoded = json.dumps(canonical, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"{encoded}\n{result}".encode()).hexdigest()


def validate_evals(state: dict[str, Any], revision: int | None, path: Path) -> None:
    """Validate a loop eval suite before dispatch or completion."""
    evals = load_evidence(path, "evals")
    _matching(evals, state, "evals")
    if evals.get("scope") != "loop" or evals.get("task_ref") != state["loop_id"]:
        raise GraphError("evals are not scoped to this loop")
    if revision is not None and evals.get("revision") != revision:
        raise GraphError("evals revision does not match the graph")
    nonempty(evals.get("verification_justification"), "evals.verification_justification")
    result = evals.get("result")
    if revision is None and is_frozen_loop_evals(evals):
        return
    if result not in {"GO", "VERIFICATION_LEVEL0"}:
        raise GraphError("evals are not graded GO")
    raw_evals = array_value(evals.get("evals"), "evals.evals")
    p0_statuses = [object_value(item, "evals.evals").get("status") for item in raw_evals]
    p0_statuses = [
        status
        for item, status in zip(raw_evals, p0_statuses)
        if object_value(item, "evals.evals").get("priority") == "P0"
    ]
    if result == "GO" and any(status != "pass" for status in p0_statuses):
        raise GraphError("evals result disagrees with its P0 statuses")
    if result == "VERIFICATION_LEVEL0" and (evals.get("verification_level") != 0 or raw_evals):
        raise GraphError("verification-level-0 result is invalid")
    grading = object_value(evals.get("grading"), "evals.grading")
    if grading.get("by") != "post_evals.py grade-loop":
        raise GraphError("evals grading stamp is missing")
    if grading.get("checksum") != _grading_checksum(evals, result):
        raise GraphError("evals grading checksum is invalid")
    amendments = array_value(evals.get("amendments"), "evals.amendments")
    if grading.get("amendments_at_grade") != len(amendments):
        raise GraphError("evals grading amendment count is stale")
    try:
        # additive: legacy_unhashed suites pass, _grading_checksum is untouched
        verify_suite(evals, stamped=True, path=path)
    except IntegrityError as error:
        raise GraphError(f"evals oracle integrity: {error}") from error


def validate_completion_evidence(
    state: dict[str, Any],
    revision: int,
    evals_path: Path,
    proof_path: Path,
    retro_path: Path,
    transcript_path: Path | None,
) -> None:
    """Validate proof, retrospective, eval, and transcript completion evidence."""
    proof = load_evidence(proof_path, "proof")
    retro = load_evidence(retro_path, "retro")
    for label, evidence in (("proof", proof), ("retro", retro)):
        _matching(evidence, state, label)
    validate_evals(state, revision, evals_path)
    proofs = array_value(proof.get("proofs"), "proof.proofs")
    if not proofs:
        raise GraphError("proof evidence is missing or not passing")
    for index, raw_proof in enumerate(proofs):
        item = object_value(raw_proof, f"proof.proofs[{index}]")
        if item.get("status") != "pass":
            raise GraphError("proof evidence is missing or not passing")
        nonempty(item.get("id"), f"proof.proofs[{index}].id")
        nonempty(item.get("cmd"), f"proof.proofs[{index}].cmd")
        nonempty(item.get("evidence"), f"proof.proofs[{index}].evidence")
    _validate_observed_proofs(proofs, transcript_path, state["loop_id"])
    schema_version = retro.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version < 1:
        raise GraphError("retro evidence is incomplete")
    if retro.get("status") != "complete":
        raise GraphError("retro evidence is incomplete")


def _exec_command(payload: dict[str, Any]) -> tuple[str, str] | None:
    if payload.get("type") == "function_call" and payload.get("name") == "exec_command":
        arguments = payload.get("arguments")
        try:
            parsed: object = (
                cast(object, cast(JsonValue, json.loads(arguments))) if isinstance(arguments, str) else arguments
            )
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            parsed = cast(dict[str, Any], parsed)
            command = parsed.get("cmd")
            if isinstance(command, str):
                return str(payload.get("call_id", "")), command.strip()
    if payload.get("type") == "custom_tool_call" and payload.get("name") == "exec":
        source = payload.get("input")
        if not isinstance(source, str) or "tools.exec_command" not in source:
            return None
        match = re.search(r'\bcmd\s*:\s*("(?:\\.|[^"\\])*")', source)
        if match:
            return str(payload.get("call_id", "")), cast(str, json.loads(match.group(1))).strip()
    return None


def _result_text(output: object) -> str | None:
    """Separate native desktop completion metadata from one unambiguous JSON result."""
    if isinstance(output, str):
        return output
    if not isinstance(output, list):
        return None
    texts: list[str] = []
    for raw in cast(list[object], output):
        if not isinstance(raw, dict):
            return None
        frame = cast(dict[str, object], raw)
        text = frame.get("text")
        if frame.get("type") not in ("input_text", "text") or not isinstance(text, str):
            return None
        texts.append(text)
    if len(texts) == 2 and re.fullmatch(r"Script completed\nWall time \d+(?:\.\d+)? seconds\nOutput:\n", texts[0]):
        return texts[1]
    return texts[0] if len(texts) == 1 else None


def parse_exec_result(payload: dict[str, Any]) -> tuple[str, bool, str | None] | None:
    """Read the native tool result associated with one foreground proof call."""
    if payload.get("type") not in {"function_call_output", "custom_tool_call_output"}:
        return None
    call_id = payload.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        return None
    output = _result_text(payload.get("output"))
    if output is None:
        return call_id, False, None
    try:
        parsed: object = cast(JsonValue, json.loads(output))
    except json.JSONDecodeError:
        return call_id, False, None
    if not isinstance(parsed, dict):
        return call_id, False, None
    parsed = cast(dict[str, Any], parsed)
    exit_code = parsed.get("exit_code")
    passed = isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code == 0
    result_loop = parsed.get("loop_id")
    if "loop_id" in parsed and not isinstance(result_loop, str):
        passed = False
    return call_id, passed, result_loop if isinstance(result_loop, str) else None


def _validate_observed_proofs(proofs: list[Any], transcript_path: Path | None, loop_id: str) -> None:
    if transcript_path is None:
        raise GraphError("proof commands were not observed in this session")
    calls: list[tuple[str, str, str | None]] = []
    results: dict[str, tuple[bool, str | None]] = {}
    transcript_loop: str | None = None
    for _, record in read_records(transcript_path, "proof transcript"):
        if record.get("type") == "turn_context":
            context = record.get("payload")
            if isinstance(context, dict) and "loop_id" in context:
                context = cast(dict[str, Any], context)
                observed_loop = context["loop_id"]
                transcript_loop = observed_loop if isinstance(observed_loop, str) else ""
            continue
        payload = event_payload(record)
        if call := _exec_command(payload):
            calls.append((*call, transcript_loop))
        if result := parse_exec_result(payload):
            results[result[0]] = (result[1], result[2])
    for raw_proof in proofs:
        raw_proof = object_value(raw_proof, "proof")
        command = raw_proof["cmd"].strip()
        matching = [
            call_id
            for call_id, observed, observed_loop in calls
            if observed == command and observed_loop in {None, loop_id}
        ]
        proof_result = results.get(matching[-1]) if matching else None
        if proof_result is None or proof_result[0] is not True or proof_result[1] not in {None, loop_id}:
            raise GraphError(f"proof command was unexecuted or last-failed: {command}")
