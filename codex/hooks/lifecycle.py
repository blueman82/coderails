#!/usr/bin/env python3
"""Generic lifecycle enforcement: JSON in, JSON out, no provider assumptions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REQUIRED_GATES = ("review", "eval", "proof", "integrity", "wiki", "teardown")
GATE_RESULTS = {"review": ("review_status", "pass"), "eval": ("result", "GO"), "proof": ("result", "pass"), "integrity": ("integrity", "pass"), "wiki": ("result", "pass"), "teardown": ("result", "pass")}


def _gate_marker_valid(kind: str, value: object, run: dict | None = None) -> bool:
    if not isinstance(value, dict) or value.get("outcome") not in {"done", "skipped"}:
        return False
    field, expected = GATE_RESULTS[kind]
    for item in value.get("evidence", []):
        if not isinstance(item, dict) or item.get("gate") != kind or item.get("provider") != "codex":
            continue
        path = item.get("artifact_path")
        if not isinstance(path, str) or not path.strip():
            continue
        try:
            artifact = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(artifact, dict) and artifact.get("schema_version") == 1 and artifact.get("gate") == kind and artifact.get("provider") == "codex" and all(artifact.get(key) == item.get(key) for key in ("run_id", "revision", "head")) and (run is None or all(artifact.get(key) == run.get(key) for key in ("run_id", "revision", "head"))) and artifact.get(field) == expected:
            return True
    return False


def validate(event: dict) -> tuple[bool, str]:
    if not isinstance(event, dict) or not isinstance(event.get("event"), str):
        return False, "event must be an object with a string event"
    state = event.get("state", {})
    if not isinstance(state, dict):
        return False, "state must be an object"
    graph = state.get("graph", {})
    nodes = graph.get("nodes", {}) if isinstance(graph, dict) else {}
    if event["event"] == "complete":
        if state.get("status") != "complete":
            return False, "complete requires state.status=complete"
        if not isinstance(nodes, dict) or any(
            not isinstance(node, dict) or node.get("outcome") not in {"done", "skipped"}
            for node in nodes.values()
        ):
            return False, "complete requires every graph node to be terminal-success"
        if state.get("mode") == "fixture" or state.get("status") == "fixture":
            return False, "fixture state cannot be complete"
        gates = state.get("gates")
        if not isinstance(gates, dict):
            return False, "complete requires gate evidence"
        run = state.get("run")
        if not isinstance(run, dict) or not all(isinstance(run.get(key), str) and run[key].strip() for key in ("run_id", "revision", "head")):
            return False, "complete requires current run identity"
        for gate in REQUIRED_GATES:
            evidence = gates.get(gate)
            if not _gate_marker_valid(gate, evidence, run):
                return False, f"complete requires evidence for gate {gate}"
        teardown = state.get("teardown")
        if not isinstance(teardown, dict) or teardown.get("provider") != "codex" or not teardown.get("evidence") or not _gate_marker_valid("teardown", teardown, run):
            return False, "complete requires Codex teardown evidence"
        retro = state.get("retro")
        if not isinstance(retro, dict) or retro.get("provider") != "codex" or retro.get("status") != "complete" or any(retro.get(key) != run.get(key) for key in ("run_id", "revision", "head")):
            return False, "complete requires valid Codex retro"
    return True, "allowed"


def main() -> int:
    event = json.load(sys.stdin)
    allowed, reason = validate(event)
    print(json.dumps({"allowed": allowed, "reason": reason}))
    return 0 if allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
