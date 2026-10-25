"""Recorded repair transition for a failed FULL graph gate, shared by both providers."""

from __future__ import annotations

import copy
import re
from typing import Any, cast

import graph_semantics
import graph_spec

KINDS = frozenset({"source", "artifact", "check"})
FAILED_ROLES = frozenset({"U4", "U4b-review", "U4b-merge-gate"})
RESET_ROLES = ("U4", "U4b-review", "U6", "U7/8", "U4b-merge-gate")
HEX_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


class RepairRefusedError(ValueError):
    """A closed repair refusal that provider CLIs surface without changing progress.json."""

    def __init__(self, code: str, detail: str) -> None:
        """Carry a stable machine reason code with a human-readable detail."""
        super().__init__(f"{code}: {detail}")
        self.code = code


def _text(value: object, limit: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit and "\n" not in value


def validate_records(state: dict[str, Any]) -> None:
    """Reject malformed or duplicate repair records before a provider trusts stamped state."""
    graph = state["graph"]
    records: object = graph.get("repair_attempts", {})
    if not isinstance(records, dict):
        raise RepairRefusedError("repair_records_invalid", "repair_attempts must be an object")
    limit = graph_spec.load_policy()["repair_attempts_max"]
    for unit, rows in cast(dict[object, object], records).items():
        if not isinstance(unit, str) or unit not in state.get("work_units", {}) or not isinstance(rows, list):
            raise RepairRefusedError("repair_records_invalid", "repair unit or rows are invalid")
        if len(cast(list[object], rows)) > limit:
            raise RepairRefusedError("repair_limit", "repair attempts exceed policy")
        seen: set[tuple[str, str]] = set()
        for raw_row in cast(list[object], rows):
            row: object = raw_row
            if not isinstance(row, dict) or set(cast(dict[object, object], row)) != {
                "failed_node",
                "kind",
                "identity",
                "diagnosis",
                "revision",
            }:
                raise RepairRefusedError("repair_records_invalid", "repair row has invalid fields")
            row = cast(dict[str, object], row)
            if not isinstance(row["failed_node"], str) or row["failed_node"] not in {
                f"{role}[{unit}]" for role in FAILED_ROLES
            }:
                raise RepairRefusedError("repair_records_invalid", "repair row has a foreign failed node")
            kind, identity = row["kind"], row["identity"]
            if (
                not isinstance(kind, str)
                or kind not in KINDS
                or not isinstance(identity, str)
                or not _text(identity, 200)
                or not _text(row["diagnosis"], 1000)
            ):
                raise RepairRefusedError("repair_records_invalid", "repair row has invalid evidence")
            if kind == "source" and HEX_SHA.fullmatch(identity) is None:
                raise RepairRefusedError("repair_records_invalid", "source repair needs a commit SHA")
            if type(row["revision"]) is not int or row["revision"] < 1:
                raise RepairRefusedError("repair_records_invalid", "repair row revision is invalid")
            key = (kind, identity)
            if key in seen:
                raise RepairRefusedError("repair_duplicate", "repair attempt identity was already used")
            seen.add(key)


def apply_failed_gates(proposal: dict[str, Any], results: dict[str, Any]) -> None:
    """Apply FULL repair policy after the pure wave transition and before the provider write."""
    graph = proposal["state"]["graph"]
    if graph.get("spec_profile") != "full":
        return
    for node_id, result in results.items():
        role, unit = graph_spec.split_id(node_id)
        if role not in FAILED_ROLES or result["outcome"] != "failed":
            continue
        node = graph["nodes"][node_id]
        if node["status"] == "hard-stop":
            continue
        attempts = graph.get("repair_attempts", {}).get(unit, [])
        if len(attempts) >= graph_spec.load_policy()["repair_attempts_max"]:
            node.update(status="hard-stop", outcome="hard-stop")
            graph["hard_stop"] = {"node": node_id, "reason": "repair attempt exhaustion"}
        else:
            node.update(status="blocked", outcome="blocked")
    proposal["ready"] = graph_semantics.ready(proposal["state"])


def record_repair(
    state: dict[str, Any], session: str, unit: str, failed_node: str, kind: str, identity: str, diagnosis: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Record one distinct repair and requeue verification and its downstream gates atomically."""
    root = copy.deepcopy(graph_semantics.validate(state))
    graph_spec.check(root)
    validate_records(root)
    graph = root["graph"]
    if root.get("session_id") != session or root.get("status") != "in-progress":
        raise RepairRefusedError("repair_owner", "session does not own an in-progress loop")
    if graph.get("spec_profile") != "full" or graph["active_wave"] is not None or graph["hard_stop"] is not None:
        raise RepairRefusedError("repair_state", "repair requires a stopped FULL graph without a hard stop")
    if unit not in root.get("work_units", {}) or failed_node not in {f"{role}[{unit}]" for role in FAILED_ROLES}:
        raise RepairRefusedError("repair_node", "failed node must be a registered unit gate")
    failed = graph["nodes"].get(failed_node)
    if not isinstance(failed, dict) or failed["status"] != "blocked" or failed["retry"]["attempts"] < 1:
        raise RepairRefusedError("repair_node", "failed gate is not blocked after a recorded failure")
    if kind not in KINDS or not _text(identity, 200) or not _text(diagnosis, 1000):
        raise RepairRefusedError("repair_evidence", "repair kind, identity and diagnosis are required")
    if kind == "source" and HEX_SHA.fullmatch(identity) is None:
        raise RepairRefusedError("repair_evidence", "source repair identity must be a commit SHA")
    rows: list[dict[str, Any]] = graph.setdefault("repair_attempts", {}).setdefault(unit, [])
    if any(row["kind"] == kind and row["identity"] == identity for row in rows):
        raise RepairRefusedError("repair_duplicate", "repair attempt identity was already used")
    if len(rows) >= graph_spec.load_policy()["repair_attempts_max"]:
        raise RepairRefusedError("repair_limit", "repair attempt limit reached")
    if failed["retry"]["attempts"] <= sum(row["failed_node"] == failed_node for row in rows):
        raise RepairRefusedError("repair_failure_missing", "no new recorded failure needs this repair")
    rows.append(
        {
            "failed_node": failed_node,
            "kind": kind,
            "identity": identity,
            "diagnosis": diagnosis,
            "revision": root["revision"],
        }
    )
    for role in RESET_ROLES:
        node: object = graph["nodes"].get(f"{role}[{unit}]")
        if isinstance(node, dict):
            cast(dict[str, Any], node).update(status="pending", outcome="pending")
    root["revision"] += 1
    graph_semantics.validate(root)
    return root, {
        "unit": unit,
        "failed_node": failed_node,
        "attempt": len(rows),
        "reason_code": "repair_recorded",
        "ready": graph_semantics.ready(root),
    }
