from __future__ import annotations

import hashlib
import json
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


def validate_evals(state: dict[str, Any], revision: int, path: Path) -> None:
    evals = _load(path, "evals")
    _matching(evals, state, "evals")
    if evals.get("scope") != "loop" or evals.get("task_ref") != state["loop_id"]:
        raise EvidenceError("evals are not scoped to this loop")
    if evals.get("revision") != revision:
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
    state: dict[str, Any], revision: int, evals_path: Path, proof_path: Path, retro_path: Path
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
        _nonempty(item.get("evidence"), f"proof.proofs[{index}].evidence")
    schema_version = retro.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version < 1:
        raise EvidenceError("retro evidence is incomplete")
    if retro.get("status") != "complete":
        raise EvidenceError("retro evidence is incomplete")
