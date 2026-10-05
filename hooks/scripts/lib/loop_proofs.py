"""Validate frozen proofs against the controller-recorded proof_results.jsonl (never the transcript)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from scripts.lib import proof_results


def validate_proofs(path: Path, state: dict[str, Any], transcript: str = "") -> str:
    """Return withdrawn-proof disclosure, raising when any frozen proof lacks a satisfied run row.

    The transcript argument is accepted for caller compatibility and ignored: proofs are verified from
    proof_results.jsonl beside proof.json, written only by `scripts/lib/proof.py run`.
    """
    results = path.with_name(proof_results.RESULTS_NAME)
    try:
        document: object = json.loads(path.read_text())
    except FileNotFoundError as error:
        try:
            rows = proof_results.read_rows(results)
        except proof_results.ChainError:
            rows = []
        code = proof_results.disposition_reason(state, rows)
        if not code:
            return ""
        proof_results.trace("proof.gate", "blocked", code, state.get("session_id"), state.get("loop_id"))
        raise ValueError(
            "no proof.json and no proof_disposition explaining why; freeze proof.json, or record "
            "`proof.py disposition --none --reason-code <code> --reason <text>` or 'none: <reason>' "
            "(a bare 'none' is rejected)"
        ) from error
    except (OSError, ValueError) as error:
        raise ValueError("proof.json is malformed (not valid JSON)") from error
    if not isinstance(document, dict):
        raise ValueError("proof.json is malformed (not an object)")
    value = cast(dict[str, Any], document)
    version = value.get("schema_version")
    if not isinstance(version, (int, float)) or isinstance(version, bool) or version < 1:
        raise ValueError("proof.json has no valid schema_version (>= 1 required)")
    proofs: object = value.get("proofs") if value.get("proofs") is not None else []
    withdrawn: object = value.get("withdrawn_proofs") if value.get("withdrawn_proofs") is not None else []
    if not isinstance(proofs, list) or not isinstance(withdrawn, list):
        raise ValueError("proof.json .proofs and .withdrawn_proofs must be arrays")
    count = len(cast(list[object], proofs)) + len(cast(list[object], withdrawn))
    if count > 100:
        raise ValueError(f"proof.json has {count} proofs+withdrawn_proofs; cap is 100")
    offenders, disclosures = proof_results.verify(value, results, state)
    if offenders:
        raise ValueError(
            "these frozen proofs are not verified: " + ", ".join(offenders) + ".\n"
            "The controller runs them: `python3 scripts/lib/proof.py run <state-dir> --all` "
            "(freeze first if proof.json changed). Withdrawn proofs require an observed failed/timeout run "
            "row and a withdrawn_reason."
        )
    return "Withdrawn proofs: " + "; ".join(disclosures) if disclosures else ""
