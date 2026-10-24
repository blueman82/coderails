"""Validate native graph eval, proof, and retrospective artifacts."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from graph_data import array_value, load_evidence, nonempty, object_value
from graph_identity import GraphError, is_frozen_loop_evals

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib import proof_results  # noqa: E402
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


def _validate_proofs(state: dict[str, Any], proof_path: Path) -> None:
    """Require a valid no-proof disposition, or every frozen proof satisfied by a controller-recorded run row."""
    results = proof_path.with_name(proof_results.RESULTS_NAME)
    if not proof_path.exists():
        try:
            rows = proof_results.read_rows(results)
        except proof_results.ChainError:
            rows = []
        code = proof_results.disposition_reason(state, rows)
        if code:
            proof_results.trace("proof.gate", "blocked", code, state["session_id"], state["loop_id"])
            raise GraphError(f"proof evidence is missing and has no valid disposition ({code})")
        return
    proof = load_evidence(proof_path, "proof")
    _matching(proof, state, "proof")
    proofs = array_value(proof.get("proofs"), "proof.proofs")
    if not proofs:
        try:
            rows = proof_results.read_rows(results)
        except proof_results.ChainError:
            rows = []
        if proof_results.disposition_reason(state, rows):
            raise GraphError("proof evidence is missing or not passing (proof_no_proofs)")
        return
    for index, raw_proof in enumerate(proofs):
        item = object_value(raw_proof, f"proof.proofs[{index}]")
        nonempty(item.get("id"), f"proof.proofs[{index}].id")
        nonempty(item.get("cmd"), f"proof.proofs[{index}].cmd")
    offenders, _ = proof_results.verify(proof, results, state)
    if offenders:
        raise GraphError("frozen proofs are not verified: " + ", ".join(offenders))


def validate_completion_evidence(
    state: dict[str, Any],
    revision: int,
    evals_path: Path,
    proof_path: Path,
    retro_path: Path,
    transcript_path: Path | None,
) -> None:
    """Validate proof, retrospective, and eval completion evidence.

    Proofs are verified from proof_results.jsonl beside proof.json (written by `scripts/lib/proof.py run`), never
    from the transcript or a `status` field. transcript_path is retained for CLI compatibility and ignored.
    """
    del transcript_path
    retro = load_evidence(retro_path, "retro")
    _matching(retro, state, "retro")
    validate_evals(state, revision, evals_path)
    _validate_proofs(state, proof_path)
    schema_version = retro.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version < 1:
        raise GraphError("retro evidence is incomplete")
    if retro.get("status") != "complete":
        raise GraphError("retro evidence is incomplete")
