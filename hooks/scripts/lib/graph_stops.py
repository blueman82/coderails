"""Pure stop-intent rows for `progress.stops`; the provider CLI owns locking and the Stop hook owns consumption."""

from __future__ import annotations

import copy
from typing import Any, cast

from hooks.scripts.lib.graph_executor import graph_semantics

STOP_CATEGORIES = ("hard-stop", "approval-gate", "awaiting-input", "complete")
STOP_REASON_CODES = (
    "work_complete",
    "needs_human_input",
    "needs_approval",
    "node_hard_stop",
    "environment_blocked",
    "other",
)


def record_stop(state: object, session: str, category: str, reason_code: str, reason: str) -> dict[str, Any]:
    """Propose the state with one more unconsumed stop row bound to the current revision."""
    root = copy.deepcopy(graph_semantics.validate(state))
    refusals = (
        (root.get("session_id") != session, "session", "session does not own this graph"),
        (category not in STOP_CATEGORIES, "stop_category", "category must be one of " + ", ".join(STOP_CATEGORIES)),
        (reason_code not in STOP_REASON_CODES, "stop_reason_code", "unknown reason_code"),
        (not reason.strip(), "stop_reason", "reason must be a non-empty string"),
        (
            category == "complete" and not graph_semantics.can_complete(root)["eligible"],
            "stop_complete",
            "complete requires a resolved graph",
        ),
    )
    for refused, code, message in refusals:
        if refused:
            raise graph_semantics.GraphSemanticError(code, message)
    stops = root.setdefault("stops", [])
    if not isinstance(stops, list) or not all(isinstance(row, dict) for row in cast(list[object], stops)):
        raise graph_semantics.GraphSemanticError("shape", "stops must be an array of objects")
    rows = cast(list[dict[str, Any]], stops)
    seq = max((row["seq"] for row in rows if isinstance(row.get("seq"), int)), default=0) + 1
    row = {
        "seq": seq,
        "category": category,
        "reason_code": reason_code,
        "reason": reason,
        "revision": root["revision"],
        "consumed": False,
    }
    rows.append(row)
    return {"state": root, "stop": copy.deepcopy(row)}
