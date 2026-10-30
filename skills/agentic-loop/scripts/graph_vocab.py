"""Closed stop vocabulary shared by both providers; materialized byte-for-byte, never redefined locally."""

from __future__ import annotations

from typing import Any, cast

STOP_CATEGORIES = ("hard-stop", "approval-gate", "awaiting-input", "complete")
STOP_REASON_CODES = (
    "work_complete",
    "needs_human_input",
    "needs_approval",
    "node_hard_stop",
    "environment_blocked",
    "other",
)
DISPOSITION_KINDS = ("clean-break", "preserve-compat")


def _filled(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def disposition_problem(kind: object, named_blocker: object, removal_ticket: object) -> str | None:
    """None when the triple is legal, else why not: preserve-compat needs both non-blank, clean-break neither."""
    if kind not in DISPOSITION_KINDS:
        return f"disposition kind must be one of {DISPOSITION_KINDS}"
    if kind == "preserve-compat" and not (_filled(named_blocker) and _filled(removal_ticket)):
        return "preserve-compat requires a non-blank named blocker and removal ticket"
    if kind == "clean-break" and (named_blocker is not None or removal_ticket is not None):
        return "clean-break forbids a named blocker and a removal ticket"
    return None


def validate_disposition(
    kind: str | None, named_blocker: str | None, removal_ticket: str | None
) -> dict[str, str] | None:
    """The object `add-unit` stores on work_units[u].disposition; None when no disposition flag was given."""
    if kind is None:
        if named_blocker is not None or removal_ticket is not None:
            raise ValueError("--named-blocker and --removal-ticket need --disposition")
        return None
    problem = disposition_problem(kind, named_blocker, removal_ticket)
    if problem:
        raise ValueError(problem)
    given = {"kind": kind, "named_blocker": named_blocker, "removal_ticket": removal_ticket}
    return {key: value.strip() for key, value in given.items() if value is not None}


def _stored(units: object) -> dict[str, object]:
    """Each unit id mapped to its raw stored disposition (None when the unit has none)."""
    if not isinstance(units, dict):
        return {}
    found: dict[str, object] = {}
    for identifier, unit in cast(dict[object, object], units).items():
        found[str(identifier)] = cast(dict[str, object], unit).get("disposition") if isinstance(unit, dict) else None
    return found


def disposition_offenders(units: object) -> list[str]:
    """Unit ids whose stored disposition is illegal (defence against hand-edited state); units without one pass."""
    found: list[str] = []
    for identifier, stored in _stored(units).items():
        if stored is None:
            continue
        fields = cast(dict[str, object], stored) if isinstance(stored, dict) else {}
        if not fields or disposition_problem(
            fields.get("kind"), fields.get("named_blocker"), fields.get("removal_ticket")
        ):
            found.append(identifier)
    return found


def disposition_report(units: object) -> dict[str, Any]:
    """The `disposition-audit` output: every unit's disposition kind (None when unset) and the offenders."""
    kinds = {
        identifier: cast(dict[str, object], stored).get("kind") if isinstance(stored, dict) else stored
        for identifier, stored in _stored(units).items()
    }
    return {"units": kinds, "offenders": disposition_offenders(units)}


def decision_pending(state: dict[str, Any], node_id: str) -> bool:
    """Block unanswered statuses and their unresolved hash-chained memory sync."""
    rows = state.get("worker_statuses", [])
    if not isinstance(rows, list):
        return True
    decisions = state.get("decisions_absorbed", [])
    if not isinstance(decisions, list):
        return True
    for raw in cast(list[object], rows):
        if not isinstance(raw, dict):
            return True
        row = cast(dict[str, Any], raw)
        if not _filled(row.get("node")) or not isinstance(row.get("decision_pending"), bool):
            return True
        if row["node"] == node_id and row["decision_pending"]:
            return True
        if row["node"] == node_id and "resolved_by_decision" in row:
            matched: list[dict[str, Any]] = []
            for item in cast(list[object], decisions):
                if isinstance(item, dict):
                    candidate = cast(dict[str, Any], item)
                    if candidate.get("seq") == row["resolved_by_decision"] and candidate.get(
                        "worker_status_seq"
                    ) == row.get("seq"):
                        matched.append(candidate)
            if len(matched) != 1:
                return True
            raw_sync: object = matched[0].get("muninn")
            if not isinstance(raw_sync, dict):
                return True
            sync = cast(dict[str, Any], raw_sync)
            if sync.get("state") not in {"written", "disabled"}:
                return True
    return False


def completion_pending_nodes(state: dict[str, Any], nodes: dict[str, Any]) -> list[str]:
    """Check stored worker answers even when their nodes are absent from the graph."""
    rows = state.get("worker_statuses", [])
    status_nodes: set[str] = set()
    if isinstance(rows, list):
        for raw in cast(list[object], rows):
            if isinstance(raw, dict):
                node = cast(dict[str, object], raw).get("node")
                if isinstance(node, str) and node.strip():
                    status_nodes.add(node)
    pending = sorted(node_id for node_id in nodes.keys() | status_nodes if decision_pending(state, node_id))
    return pending or (["worker_statuses"] if decision_pending(state, "") else [])


def decision_sync_pending(state: dict[str, Any]) -> bool:
    """Block any hashed decision whose Muninn write has not reached a final accepted state."""
    rows = state.get("decisions_absorbed", [])
    if not isinstance(rows, list):
        return True
    for value in cast(list[object], rows):
        if not isinstance(value, dict):
            continue  # historic prose rows have no sync contract
        row = cast(dict[str, Any], value)
        if not row.get("row_sha256"):
            continue
        raw_sync: object = row.get("muninn")
        if not isinstance(raw_sync, dict):
            return True
        sync = cast(dict[str, Any], raw_sync)
        if sync.get("state") in {"written", "disabled"}:
            continue
        if (
            sync.get("state") == "degraded"
            and "worker_status_seq" not in row
            and set(sync) == {"state", "id", "reason_code"}
            and sync["id"] is None
            and _filled(sync["reason_code"])
        ):
            continue
        return True
    return False
