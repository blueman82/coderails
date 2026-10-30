"""Re-derive current Claude evidence at completion, including every prior attempt."""

from __future__ import annotations

import hashlib
from typing import Any

from .graph_evidence import child_identity, notifications, object_value, spawns, transcript
from .graph_evidence_bind import SKIP_PREFIXES, check_record, provenance, terminal, used_references
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
    fields = {"kind", "attempt", "wave_id", "reason", "evidence_sha256"}
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
    ):
        raise ValueError("invalid scout skip evidence")
    wave = object_value(history.get(ref["wave_id"]), "native wave history entry")
    if (
        type(wave.get("cursor")) is not int
        or node_id not in wave.get("nodes", [])
        or type(wave.get("revision")) is not int
        or any(
            row["node_id"] == node_id and row["wave_id"] == ref["wave_id"] and row["line"] > wave["cursor"]
            for row in rows
        )
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


def validate_reference(
    state: dict[str, Any], node_id: str, ref: dict[str, Any], rows: list[dict[str, Any]], history: dict[str, Any]
) -> dict[str, Any]:
    """Recheck original role, wave ownership, cursor and raw spawn UUID."""
    required = {"kind", "attempt", "wave_id", "tool_use_id", "record_uuid", "subagent_type", "outcome"}
    if set(ref) not in (required, required | {"agent_id"}) or ref.get("kind") != "claude_agent":
        raise ValueError("native evidence does not have the bound object shape")
    if ref["outcome"] not in {"done", "skipped", "failed", "stale"}:
        raise ValueError("invalid native attempt outcome")
    matches = [row for row in rows if row["tool_use_id"] == ref["tool_use_id"]]
    if len(matches) != 1:
        raise ValueError("native bound spawn no longer resolves uniquely")
    row = matches[0]
    if row["node_id"] != node_id or any(row[key] != state[key] for key in ("session_id", "loop_id")):
        raise ValueError("native bound spawn belongs to another node or session")
    for key in ("wave_id", "record_uuid", "subagent_type"):
        if row[key] != ref[key]:
            raise ValueError(f"native bound spawn {key} no longer matches")
    wave = object_value(history.get(row["wave_id"]), "native wave history entry")
    if (
        type(wave.get("cursor")) is not int
        or row["line"] <= wave["cursor"]
        or node_id not in wave.get("nodes", [])
        or wave.get("revision") != row["revision"]
    ):
        raise ValueError("native bound spawn is outside its original wave cursor or node set")
    check_record(state, row)
    return row
