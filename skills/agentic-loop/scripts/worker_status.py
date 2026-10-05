#!/usr/bin/env python3
"""Typed worker statuses that need a human: schema, validator and decision-request helper (stdlib, py3.9).

Standalone on purpose: NOT wired into graph_semantics record-wave (its outcome/keyset demands stay unchanged).
Wiring point: the orchestrator's U4 step (execution-graph.md) and the SKILL.md report-back contract. A worker
returns one of these as its report; the orchestrator calls validate(), then to_decision_request(), and is the
only party that asks the human.
"""

from __future__ import annotations

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
