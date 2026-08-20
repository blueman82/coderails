from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


class EvidenceError(ValueError):
    pass


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceError(f"{label} must be an object")
    return value


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceError(f"{label} must be a non-empty string")
    return value


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            return _object(json.load(handle), label)
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{label} is missing or invalid: {error}") from error


def _matching(evidence: dict[str, Any], state: dict[str, Any], label: str) -> None:
    if evidence.get("session_id") != state["session_id"] or evidence.get("loop_id") != state["loop_id"]:
        raise EvidenceError(f"{label} belongs to a different loop")


def _grading_checksum(evals: dict[str, Any], result: str) -> str:
    raw_evals = evals.get("evals")
    if not isinstance(raw_evals, list):
        raise EvidenceError("evals.evals must be an array")
    canonical = []
    for index, raw_eval in enumerate(raw_evals):
        item = _object(raw_eval, f"evals.evals[{index}]")
        canonical.append({key: item.get(key) for key in ("id", "priority", "status")})
    encoded = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(f"{encoded}\n{result}".encode()).hexdigest()


def validate_evals(state: dict[str, Any], revision: int | None, path: Path) -> None:
    evals = _load(path, "evals")
    _matching(evals, state, "evals")
    if evals.get("scope") != "loop" or evals.get("task_ref") != state["loop_id"]:
        raise EvidenceError("evals are not scoped to this loop")
    if revision is not None and evals.get("revision") != revision:
        raise EvidenceError("evals revision does not match the graph")
    _nonempty(evals.get("verification_justification"), "evals.verification_justification")
    result = evals.get("result")
    if result not in {"GO", "VERIFICATION_LEVEL0"}:
        raise EvidenceError("evals are not graded GO")
    raw_evals = evals.get("evals")
    if not isinstance(raw_evals, list):
        raise EvidenceError("evals.evals must be an array")
    p0_statuses = [
        item.get("status")
        for item in raw_evals
        if isinstance(item, dict) and item.get("priority") == "P0"
    ]
    if result == "GO" and any(status != "pass" for status in p0_statuses):
        raise EvidenceError("evals result disagrees with its P0 statuses")
    if result == "VERIFICATION_LEVEL0" and (evals.get("verification_level") != 0 or raw_evals):
        raise EvidenceError("verification-level-0 result is invalid")
    grading = _object(evals.get("grading"), "evals.grading")
    if grading.get("by") != "post_evals.sh grade-loop":
        raise EvidenceError("evals grading stamp is missing")
    if grading.get("checksum") != _grading_checksum(evals, result):
        raise EvidenceError("evals grading checksum is invalid")
    amendments = evals.get("amendments")
    if not isinstance(amendments, list) or grading.get("amendments_at_grade") != len(amendments):
        raise EvidenceError("evals grading amendment count is stale")


def validate_completion_evidence(
    state: dict[str, Any],
    revision: int,
    evals_path: Path,
    proof_path: Path,
    retro_path: Path,
    transcript_path: Path | None,
) -> None:
    proof = _load(proof_path, "proof")
    retro = _load(retro_path, "retro")
    for label, evidence in (("proof", proof), ("retro", retro)):
        _matching(evidence, state, label)
    validate_evals(state, revision, evals_path)
    proofs = proof.get("proofs")
    if not isinstance(proofs, list) or not proofs:
        raise EvidenceError("proof evidence is missing or not passing")
    for index, raw_proof in enumerate(proofs):
        item = _object(raw_proof, f"proof.proofs[{index}]")
        if item.get("status") != "pass":
            raise EvidenceError("proof evidence is missing or not passing")
        _nonempty(item.get("id"), f"proof.proofs[{index}].id")
        _nonempty(item.get("cmd"), f"proof.proofs[{index}].cmd")
        _nonempty(item.get("evidence"), f"proof.proofs[{index}].evidence")
    _validate_observed_proofs(proofs, transcript_path, state["loop_id"])
    schema_version = retro.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version < 1:
        raise EvidenceError("retro evidence is incomplete")
    if retro.get("status") != "complete":
        raise EvidenceError("retro evidence is incomplete")


def _exec_command(payload: dict[str, Any]) -> tuple[str, str] | None:
    if payload.get("type") == "function_call" and payload.get("name") == "exec_command":
        arguments = payload.get("arguments")
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict) and isinstance(parsed.get("cmd"), str):
            return str(payload.get("call_id", "")), parsed["cmd"].strip()
    if payload.get("type") == "custom_tool_call" and payload.get("name") == "exec":
        source = payload.get("input")
        if not isinstance(source, str) or "tools.exec_command" not in source:
            return None
        match = re.search(r'\bcmd\s*:\s*("(?:\\.|[^"\\])*")', source)
        if match:
            return str(payload.get("call_id", "")), json.loads(match.group(1)).strip()
    return None


def _exec_result(payload: dict[str, Any]) -> tuple[str, bool, str | None] | None:
    if payload.get("type") not in {"function_call_output", "custom_tool_call_output"}:
        return None
    call_id = payload.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        return None
    output = payload.get("output")
    if isinstance(output, list):
        output = "".join(
            item.get("text", "")
            for item in output
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    if not isinstance(output, str):
        return call_id, False, None
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return call_id, False, None
    if not isinstance(parsed, dict):
        return call_id, False, None
    exit_code = parsed.get("exit_code")
    passed = isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code == 0
    result_loop = parsed.get("loop_id")
    if "loop_id" in parsed and not isinstance(result_loop, str):
        passed = False
    return call_id, passed, result_loop if isinstance(result_loop, str) else None


def _validate_observed_proofs(proofs: list[Any], transcript_path: Path | None, loop_id: str) -> None:
    if transcript_path is None:
        raise EvidenceError("proof commands were not observed in this session")
    calls: list[tuple[str, str, str | None]] = []
    results: dict[str, tuple[bool, str | None]] = {}
    transcript_loop: str | None = None
    try:
        with transcript_path.open(encoding="utf-8") as transcript:
            for line in transcript:
                record = json.loads(line)
                if isinstance(record, dict) and record.get("type") == "turn_context":
                    context = record.get("payload")
                    if isinstance(context, dict) and "loop_id" in context:
                        observed_loop = context["loop_id"]
                        transcript_loop = observed_loop if isinstance(observed_loop, str) else ""
                    continue
                payload = record.get("payload", record) if isinstance(record, dict) else {}
                if not isinstance(payload, dict):
                    continue
                if call := _exec_command(payload):
                    calls.append((*call, transcript_loop))
                if result := _exec_result(payload):
                    results[result[0]] = (result[1], result[2])
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceError(f"proof transcript is missing or invalid: {error}") from error
    for raw_proof in proofs:
        command = raw_proof["cmd"].strip()
        matching = [
            call_id
            for call_id, observed, observed_loop in calls
            if observed == command and observed_loop in {None, loop_id}
        ]
        result = results.get(matching[-1]) if matching else None
        if result is None or result[0] is not True or result[1] not in {None, loop_id}:
            raise EvidenceError(f"proof command was unexecuted or last-failed: {command}")
