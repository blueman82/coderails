#!/usr/bin/env python3
"""Typed worker results: human-needing statuses, the done-result final_report, and the record-wave pre-processor.

Pure (stdlib, py3.9) and mirrored byte-for-byte into the Codex plugin. graph_semantics stays untouched: both providers'
`record_wave` call `prepare()` first, hand the translated results to the unchanged core, then `record_into()` and a
`graph_stops` row on the post-record state, all inside the one locked write. `append_decision()` is the pure core of
`graph.py record-decision`, which answers a recorded status.

A worker that must stop for a human returns one of STATUSES instead of an {outcome, evidence} result. `prepare()`
rejects a malformed one (the whole report, atomically) and translates a valid one to core outcome `failed`, which
consumes one retry (documented limit: the core has no "needs a human" outcome). A done result for a dispatch whose
record has `final_report_required` must carry a valid `final_report`; it is stripped before the core call and stored.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, cast

STATUSES = ("NEEDS_DECISION", "OUTSIDE_SCOPE", "IRREVERSIBLE_ACTION")
CONFIDENCE = ("verified", "inferred", "guess")
COMMON = ("status", "worker", "summary", "confidence")
EXTRA = {
    "NEEDS_DECISION": ("question", "options", "recommended"),
    "OUTSIDE_SCOPE": ("requested_action", "scope_boundary"),
    "IRREVERSIBLE_ACTION": ("action", "why_irreversible", "rollback"),
}
REASONS = ("ok", "not_an_object", "unknown_status", "missing_field", "unknown_field", "bad_field")
STOP_FOR = {  # (category, reason_code) of the typed stop row, from the closed graph_vocab vocabulary
    "NEEDS_DECISION": ("awaiting-input", "needs_human_input"),
    "OUTSIDE_SCOPE": ("approval-gate", "needs_approval"),
    "IRREVERSIBLE_ACTION": ("approval-gate", "needs_approval"),
}
REPORT_KEYS = ("claims", "did_not_verify")
TAGS = ("resolved", "unverifiable")
REFUSAL_CODES = (*(f"worker_status_{reason}" for reason in REASONS[1:]), "final_report_invalid")


class WorkerResultError(ValueError):
    """A whole-report rejection carrying one closed reason code (a member of REFUSAL_CODES)."""

    def __init__(self, code: str, message: str, node: str | None = None) -> None:
        """Keep the code and implicated node; str() shows the code like the other coded refusals."""
        super().__init__(f"{message} [reason_code={code}]")
        self.code, self.message, self.node = code, message, node


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _options_ok(data: dict[str, Any]) -> bool:
    options = data["options"]
    if not isinstance(options, list) or len(cast("list[object]", options)) < 2:
        return False
    items = cast("list[object]", options)
    recommended = data["recommended"]
    named = all(_text(item) for item in items) and _text(data["question"])
    return named and (recommended is None or recommended in items)


def validate(result: object) -> str:
    """Return a stable reason code: "ok" or the first problem (never raises)."""
    if not isinstance(result, dict):
        return "not_an_object"
    data = cast("dict[str, Any]", result)
    status = data.get("status")
    if not isinstance(status, str) or status not in EXTRA:
        return "unknown_status"
    keys = COMMON + EXTRA[status]
    if any(key not in data for key in keys):
        return "missing_field"
    if any(key not in keys for key in data):
        return "unknown_field"
    if not all(_text(data[key]) for key in COMMON) or data["confidence"] not in CONFIDENCE:
        return "bad_field"
    if status == "NEEDS_DECISION":
        return "ok" if _options_ok(data) else "bad_field"
    return "ok" if all(_text(data[key]) for key in EXTRA[status]) else "bad_field"


def classify_result(result: object) -> str:
    """Return "typed" when the result is a worker status attempt (carries a `status` key), else "untyped"."""
    return "typed" if isinstance(result, dict) and "status" in cast("dict[str, Any]", result) else "untyped"


def _items(value: object) -> list[dict[str, Any]] | None:
    """The list's entries when it is a list of objects, else None."""
    if not isinstance(value, list):
        return None
    entries = cast("list[object]", value)
    if not all(isinstance(entry, dict) for entry in entries):
        return None
    return cast("list[dict[str, Any]]", entries)


def _claim_ok(claim: dict[str, Any]) -> bool:
    if not set(claim) <= {"text", "label", "source"} or not {"text", "label"} <= set(claim):
        return False
    if not _text(claim["text"]) or claim["label"] not in CONFIDENCE:
        return False
    source = claim.get("source")
    return _text(source) if claim["label"] == "verified" or source is not None else True


def _unverified_ok(entry: dict[str, Any]) -> bool:
    return (
        set(entry) == {"item", "tag", "reason"}
        and _text(entry["item"])
        and entry["tag"] in TAGS
        and _text(entry["reason"])
    )


def validate_final_report(report: object) -> str:
    """Return "ok" or the first problem of a done result's final_report (never raises).

    {claims: [{text, label verified|inferred|guess, source?}], did_not_verify: [{item, tag resolved|unverifiable,
    reason}]}. claims must be non-empty and a `verified` claim must cite a source; did_not_verify may be empty.
    """
    if not isinstance(report, dict):
        return "not_an_object"
    data = cast("dict[str, Any]", report)
    if any(key not in data for key in REPORT_KEYS):
        return "missing_field"
    if any(key not in REPORT_KEYS for key in data):
        return "unknown_field"
    claims, unverified = _items(data["claims"]), _items(data["did_not_verify"])
    if not claims or unverified is None:
        return "bad_field"
    ok = all(_claim_ok(claim) for claim in claims) and all(_unverified_ok(entry) for entry in unverified)
    return "ok" if ok else "bad_field"


def _record(state: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    """The begin-wave dispatch record of this node in the active wave, or None (pre-conversion state)."""
    graph = cast("dict[str, Any]", state["graph"])
    active = cast("dict[str, Any] | None", graph.get("active_wave"))
    records = cast("dict[str, dict[str, Any]]", graph.get("dispatches") or {})
    for record in records.values():
        if active and record.get("node_id") == node_id and record.get("wave_id") == active["wave_id"]:
            return record
    return None


def prepare(
    state: dict[str, Any], results: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Pre-process a wave report: (core_results, statuses, final_reports). Raises WorkerResultError, writes nothing.

    A result with a `status` key must pass validate(). On any other result a `final_report` (if present) must validate
    and is moved out of the core's way; a `done` outcome without one is refused when the node's dispatch record has
    `final_report_required`. A node with no dispatch record (pre-conversion) and no final_report is passed through.
    """
    core: dict[str, Any] = {}
    statuses: list[dict[str, Any]] = []
    reports: dict[str, Any] = {}
    for node_id, result in results.items():
        if classify_result(result) == "typed":
            code = validate(result)
            if code != "ok":
                raise WorkerResultError(f"worker_status_{code}", f"worker status for {node_id} is {code}", node_id)
            payload = cast("dict[str, Any]", result)
            statuses.append({"node": node_id, "status": payload["status"], "payload": dict(payload)})
            core[node_id] = {"outcome": "failed", "evidence": f"{payload['status']}: {payload['summary']}"}
            continue
        if not isinstance(result, dict) or ("final_report" not in result and _record(state, node_id) is None):
            core[node_id] = result  # not an object, or nothing to extract and no dispatch record: the core decides
            continue
        body = dict(cast("dict[str, Any]", result))
        report = body.pop("final_report", None)
        record = _record(state, node_id)
        if report is None and record and record.get("final_report_required") and body.get("outcome") == "done":
            raise WorkerResultError("final_report_invalid", f"done result for {node_id} lacks a final_report", node_id)
        if report is not None:
            problem = validate_final_report(report)
            if problem != "ok":
                raise WorkerResultError("final_report_invalid", f"final_report for {node_id} is {problem}", node_id)
            reports[node_id] = report
        core[node_id] = body
    return core, statuses, reports


def record_into(
    proposed: dict[str, Any], wave_id: str, statuses: list[dict[str, Any]], reports: dict[str, Any]
) -> None:
    """Append the status rows (bound to the post-record revision) and store the final reports on the proposed state."""
    if reports:
        proposed.setdefault("final_reports", {}).update(reports)
    if not statuses:
        return
    rows = proposed.setdefault("worker_statuses", [])
    seq = max((row["seq"] for row in rows if isinstance(row.get("seq"), int)), default=0)
    for offset, status in enumerate(statuses, 1):
        rows.append(
            {
                "seq": seq + offset,
                "node": status["node"],
                "wave_id": wave_id,
                "status": status["status"],
                "payload": status["payload"],
                "decision_pending": True,
                "revision": proposed["revision"],
            }
        )


def stop_for(statuses: list[dict[str, Any]]) -> tuple[str, str, str]:
    """(category, reason_code, reason) of the ONE stop row for a record: approval-gate outranks awaiting-input."""
    pairs = [STOP_FOR[status["status"]] for status in statuses]
    category, code = next((pair for pair in pairs if pair[0] == "approval-gate"), pairs[0])
    reason = "worker status: " + "; ".join(f"{s['node']} {s['status']} ({s['payload']['summary']})" for s in statuses)
    return category, code, reason


def append_decision(
    state: dict[str, Any], session: str, fields: dict[str, str | None], worker_status_seq: int | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (proposed state, row) with one typed row appended to `decisions_absorbed`; writes nothing.

    `fields` carries phase, decision, chosen and optionally flip_condition (all typed flags, no prose parsing). With
    `worker_status_seq` the named `worker_statuses` row is marked resolved. The revision is not bumped: a decision
    is not a graph change. Raises WorkerResultError with a `record_decision_refused_*` code.
    """
    if state.get("session_id") != session:
        raise WorkerResultError("record_decision_refused_foreign", "session does not own this graph")
    for name, value in fields.items():
        if (value is not None or name != "flip_condition") and not _text(value):
            raise WorkerResultError("record_decision_refused_field", f"--{name.replace('_', '-')} must be non-blank")
    ledger = state.get("decisions_absorbed", [])
    if not isinstance(ledger, list) or not all(isinstance(row, dict) for row in cast("list[object]", ledger)):
        raise WorkerResultError("record_decision_refused_state", "decisions_absorbed must be an array of objects")
    proposed = copy.deepcopy(state)
    rows = cast("list[dict[str, Any]]", proposed.setdefault("decisions_absorbed", []))
    seq = max((row["seq"] for row in rows if isinstance(row.get("seq"), int)), default=0) + 1
    row: dict[str, Any] = {"seq": seq}
    row.update({key: value.strip() for key, value in fields.items() if value is not None})
    if worker_status_seq is not None:
        row["worker_status_seq"] = worker_status_seq
        statuses = _items(proposed.get("worker_statuses") or []) or []
        named = [status for status in statuses if status.get("seq") == worker_status_seq]
        if not named or named[0].get("decision_pending") is not True:
            raise WorkerResultError("record_decision_refused_status", f"no pending worker status {worker_status_seq}")
        named[0].update(decision_pending=False, resolved_by_decision=seq)
    row.update(revision=state["revision"], recorded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    rows.append(row)
    return proposed, row


def to_decision_request(result: dict[str, Any]) -> dict[str, Any]:
    """Orchestrator-only: turn a valid status into the human-facing request. Raises ValueError with the code."""
    code = validate(result)
    if code != "ok":
        raise ValueError(code)
    status = result["status"]
    if status == "NEEDS_DECISION":
        ask, options = result["question"], list(result["options"])
    elif status == "OUTSIDE_SCOPE":
        ask = f"Worker asked to go outside scope ({result['scope_boundary']}): {result['requested_action']}. Allow it?"
        options = ["allow", "deny"]
    else:
        ask = (
            f"Worker wants an irreversible action: {result['action']} ({result['why_irreversible']}). "
            f"Rollback: {result['rollback']}. Proceed?"
        )
        options = ["proceed", "do not proceed"]
    return {
        "status": status,
        "from_worker": result["worker"],
        "ask": ask,
        "options": options,
        "recommended": result.get("recommended"),
        "context": f"[{result['confidence']}] {result['summary']}",
    }
