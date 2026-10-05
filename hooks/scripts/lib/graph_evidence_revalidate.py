"""Re-derive current Claude evidence at completion, including every prior attempt."""

from __future__ import annotations

from typing import Any

from .graph_evidence import child_identity, notifications, object_value, spawns, transcript
from .graph_evidence_bind import provenance, terminal, used_references


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
    return row
