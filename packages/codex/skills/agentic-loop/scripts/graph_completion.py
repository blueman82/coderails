"""Apply native completion evidence and independent work-unit gates."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

import graph_semantics
from graph_evidence import validate_completion_evidence, validate_worker_evidence
from graph_identity import GraphError
from graph_io import load as _load
from graph_io import locked as _locked
from graph_io import object_value as _object
from graph_io import write as _write
from graph_recovery import traced_refusal
from graph_vocab import disposition_offenders


def _orders() -> Any:  # noqa: ANN401
    """Load the Codex provider's D4 module lazily to avoid its graph-completion import cycle."""
    provider = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(provider))
    from scripts.lib import orders_completion  # noqa: PLC0415

    return orders_completion


def validate_work_units(state: dict[str, Any]) -> None:
    """Require each optional implementation unit to be done or reasonedly dropped."""
    units = state.get("work_units")
    if units is None:
        return
    if not isinstance(units, dict):
        raise GraphError("work_units must be an object")
    for unit_id, unit in cast(dict[object, object], units).items():
        if not isinstance(unit_id, str) or not unit_id.strip() or not isinstance(unit, dict):
            raise GraphError("work_units entries must be named objects")
        unit = cast(dict[str, object], unit)
        if unit.get("status") == "done":
            continue
        reason = unit.get("dropped_reason")
        if unit.get("status") == "dropped" and isinstance(reason, str) and reason.strip():
            continue
        raise GraphError(f"work unit {unit_id} is unfinished or malformed")
    if bad := disposition_offenders(cast(dict[str, Any], units)):
        raise GraphError("work units have an illegal disposition: " + ", ".join(bad))


def _validate_completion(
    path: Path,
    state: dict[str, Any],
    session: str,
    revision: int,
    evals_path: Path,
    proof_path: Path,
    retro_path: Path,
    transcript_path: Path | None,
) -> list[str]:
    if state.get("proof_disposition") is not None and proof_path.absolute() != path.with_name("proof.json").absolute():
        raise GraphError("proof path must be beside progress.json for a no-proof decision")
    if state["session_id"] != session:
        raise GraphError("session does not own this loop")
    eligibility = graph_semantics.can_complete(state)
    if not eligibility["eligible"]:
        raise GraphError("cannot complete graph: " + ", ".join(eligibility["blockers"]))
    validate_work_units(state)
    validate_worker_evidence(state)
    return validate_completion_evidence(state, revision, evals_path, proof_path, retro_path, transcript_path)


def _result(state: dict[str, Any], disclosures: list[str]) -> dict[str, Any]:
    """The completion record; `disclosures` (Muninn degrades) appears only when there is something to disclose."""
    result: dict[str, Any] = {"status": "complete", "loop_id": state["loop_id"], "revision": state["revision"]}
    return {**result, "disclosures": disclosures} if disclosures else result


def complete(
    path: Path, session: str, evals_path: Path, proof_path: Path, retro_path: Path, transcript_path: Path | None
) -> dict[str, Any]:
    """Prepare orders, save validated completion, then apply the lifecycle outside both locks."""
    current = _load(path)
    if current["status"] != "complete":
        _validate_completion(
            path, current, session, current["revision"], evals_path, proof_path, retro_path, transcript_path
        )
    orders = _orders()
    try:
        digest = orders.prepare(path, session, current["loop_id"]) if current["status"] != "complete" else None
    except ValueError as error:
        raise GraphError(str(error)) from error
    with _locked(path):
        state = _load(path)
        already_complete = state["status"] == "complete"
        if already_complete:
            completion = _object(state.get("completion"), "completion")
            revision = completion.get("revision")
            if isinstance(revision, bool) or not isinstance(revision, int) or revision != state["revision"] - 1:
                raise GraphError("graph has no valid completion record")
        else:
            revision = state["revision"]
        with traced_refusal(path, state, "complete", session):
            disclosures = _validate_completion(
                path, state, session, revision, evals_path, proof_path, retro_path, transcript_path
            )
            if not already_complete:
                if digest is None:
                    raise GraphError("order_source_mismatch")
                try:
                    orders.validate_prepared(path, state, digest)
                except ValueError as error:
                    raise GraphError(str(error)) from error
        if not already_complete:
            state["status"] = "complete"
            state["revision"] += 1
            state["completion"] = {"revision": revision}
            _write(path, state, preserve_updated_at=True)
    result = _result(state, disclosures)
    result.update(orders.finish(path, session, state["loop_id"]))
    return result


def verify_completion(
    path: Path, session: str, evals_path: Path, proof_path: Path, retro_path: Path, transcript_path: Path | None
) -> dict[str, Any]:
    """Revalidate the recorded completion against live native evidence."""
    state = _load(path)
    completion = _object(state.get("completion"), "completion")
    revision = completion.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int):
        raise GraphError("graph completion revision must be an integer")
    if state["status"] != "complete" or revision != state["revision"] - 1:
        raise GraphError("graph has no valid completion record")
    with traced_refusal(path, state, "verify-completion", session):
        disclosures = _validate_completion(
            path, state, session, revision, evals_path, proof_path, retro_path, transcript_path
        )
        try:
            _orders().status(path, session)
        except (OSError, ValueError) as error:
            raise GraphError(f"standing-orders teardown pending: {error}") from error
    return _result(state, disclosures)
