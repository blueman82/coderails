"""Re-derive current Claude evidence at completion, including every prior attempt."""

from __future__ import annotations

import hashlib
from typing import Any

from .graph_evidence import child_identity, notifications, object_value, spawns, transcript, validate_reference
from .graph_evidence_bind import SKIP_PREFIXES, check_skip_wave, provenance, terminal, used_references
from .graph_scout_approval import approval


def revalidate_all(state: dict[str, Any]) -> None:
    """Reject missing, forged, reused or subsequently corrupted native evidence."""
    session = state["session_id"]
    path = transcript(session)
    rows, notices = spawns(path, session), notifications(path, session)
    used_references(state)
    history = object_value(state["graph"].get("wave_history", {}), "native wave history")
    for node_id, node in state["graph"]["nodes"].items():
        if node_id in state["graph"]["joins"]:
            continue
        refs = [object_value(item, "structured native evidence") for item in node["evidence"] if provenance(item)]
        expected = node["retry"]["attempts"] + node["respawn"]["generation"]
        if node["status"] in {"done", "skipped", "stale"}:
            expected += 1
        if {item.get("attempt") for item in refs} != set(range(1, expected + 1)):
            raise ValueError(f"node {node_id} has missing or forged native attempt history")
        ordering: dict[int, set[str]] = {}
        for ref in refs:
            if ref.get("kind") == "graph_skip":
                if sum(item.get("attempt") == ref.get("attempt") for item in refs) != 1:
                    raise ValueError(f"node {node_id} has missing or forged native attempt history")
                validate_skip_reference(state, node_id, node, ref, rows, history)
                ordering.setdefault(ref["attempt"], set()).add(ref["wave_id"])
                continue
            row = validate_reference(state, node_id, ref, rows, history)
            ordering.setdefault(ref["attempt"], set()).add(row["wave_id"])
            completed = ref["outcome"] == "done"
            agent = child_identity(path, session, row, completed, ref["outcome"] == "failed")
            if ref.get("agent_id", "") != agent:
                raise ValueError("bound native child identity no longer matches")
            if completed:
                terminal(row, notices, agent)
        if any(len(waves) != 1 for waves in ordering.values()):
            raise ValueError("one native attempt spans conflicting waves")
        revisions = [history[next(iter(ordering[index]))]["revision"] for index in sorted(ordering)]
        if revisions != sorted(set(revisions)):
            raise ValueError("native attempt order is not strictly increasing")
        if node["status"] == "done" and not any(
            item["attempt"] == expected and item["outcome"] == "done" for item in refs
        ):
            raise ValueError(f"node {node_id} lacks successful final native evidence")


def validate_skip_reference(
    state: dict[str, Any],
    node_id: str,
    node: dict[str, Any],
    ref: dict[str, Any],
    rows: list[dict[str, Any]],
    history: dict[str, Any],
) -> None:
    """Recheck a scoped no-work or owner-approved scout skip."""
    approved = ref.get("reason") == "non_independent"
    prefix = "non_independent:" if approved else SKIP_PREFIXES.get(node_id)
    fields = {"kind", "attempt", "wave_id", "reason", "evidence_sha256", "cursor"}
    if approved:
        fields |= {"request_line", "request_sha256", "approval_line", "approval_sha256"}
    if (
        prefix is None
        or set(ref) != fields
        or type(ref.get("attempt")) is not int
        or ref["attempt"] != node["retry"]["attempts"] + 1
        or (not approved and ref["attempt"] != 1)
        or (approved and (node_id != "S2.5" or ref["attempt"] < 2))
        or ref.get("reason") != prefix[:-1]
        or node["status"] != "skipped"
        or node["respawn"]["generation"] != 0
        or type(ref.get("cursor")) is not int
        or ref["cursor"] < 0
    ):
        raise ValueError("invalid scout skip evidence")
    check_skip_wave(state, node_id, ref["attempt"], ref["wave_id"], ref["cursor"])
    wave = object_value(history.get(ref["wave_id"]), "native wave history entry")
    if any(
        row["node_id"] == node_id and row["wave_id"] == ref["wave_id"] and row["line"] > wave["cursor"] for row in rows
    ):
        raise ValueError("scout skip no longer matches its native wave")
    matching = [
        item
        for item in node["evidence"]
        if isinstance(item, str)
        and item.startswith(prefix)
        and item[len(prefix) :].strip()
        and hashlib.sha256(item.encode()).hexdigest() == ref["evidence_sha256"]
    ]
    if len(matching) != 1:
        raise ValueError("scout skip reason no longer matches its evidence")
    if approved:
        expected_approval = approval(state, node_id, ref["attempt"], rows)
        if any(ref.get(key) != value for key, value in expected_approval.items()):
            raise ValueError("scout skip approval reference changed")
