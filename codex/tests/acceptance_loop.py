#!/usr/bin/env python3
"""Run a resumable local A || B -> C Codex graph acceptance loop."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "codex"))
from runtime.graph import REQUIRED_GATES, apply_work_unit_disposition, build_graph, execute, gate_snapshot, prepare_implementations  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--phase-graph", action="store_true", help="run every node parsed from execution-graph.md")
    args = parser.parse_args()
    command = [sys.executable, "-c", "print('local Codex fixture gate')"]
    fixture_nodes = ("A", "B", "C")
    implementations = {
        node: {"command": command, "provider": "codex", "skill_id": f"fixture.{node}", "implementation_path": "codex/tests/acceptance_loop.py"}
        for node in fixture_nodes
    }
    if args.state.exists():
        graph = json.loads(args.state.read_text(encoding="utf-8"))["graph"]
    else:
        graph = build_graph() if args.phase_graph else build_graph(fixture_nodes, joins={"C": ("A", "B")})
        if args.phase_graph:
            implementations = {
                node: {"command": command, "provider": "codex", "skill_id": f"fixture.{node}", "path": "codex/tests/acceptance_loop.py"}
                for node in graph["nodes"]
            }
    if args.phase_graph:
        implementations = {
            node: {"command": command, "provider": "codex", "skill_id": f"fixture.{node}", "implementation_path": "codex/tests/acceptance_loop.py"}
            for node in graph["nodes"]
        }
        graph["artifacts"] = {"kind": "fixture", "external_gates": "not executed"}

    if not args.phase_graph:
        for kind in REQUIRED_GATES:
            name = f"fixture-gate-{kind}"
            graph["nodes"][name] = {"status": "pending", "outcome": "pending", "dispatch": True, "retry": {"attempts": 0, "max": 1}, "name": name}
            graph["edges"].append({"from": "C", "to": name})
    apply_work_unit_disposition(graph, None)
    config = {"mode": "fixture", "nodes": {}, "gates": {}}
    for node in graph["nodes"]:
        config["nodes"][node] = {"command": command, "provider": "codex", "skill_id": f"fixture.{node}", "implementation_path": "codex/tests/acceptance_loop.py"}
    gate_nodes = [name for name, value in graph["nodes"].items() if value.get("dispatch", True) and "[i]" not in name][:len(REQUIRED_GATES)]
    if not args.phase_graph:
        gate_nodes = [f"fixture-gate-{kind}" for kind in REQUIRED_GATES]
    for kind, node in zip(REQUIRED_GATES, gate_nodes):
        config["gates"][kind] = {"node": node, "command": command, "provider": "codex", "skill_id": f"fixture.gate.{kind}", "implementation_path": "codex/tests/acceptance_loop.py"}
    implementations, errors = prepare_implementations(graph, config)
    graph["configuration_errors"] = errors

    def persist(value: dict) -> None:
        print(json.dumps({"wave": [name for name, node in value["nodes"].items() if node["outcome"] != "pending"]}))

    execute(graph, implementations if not errors else {}, state_path=args.state, persist=persist)
    state = json.loads(args.state.read_text(encoding="utf-8"))
    gates = gate_snapshot(graph, config)
    successful = not errors and all(node.get("outcome") in {"done", "skipped"} for node in graph["nodes"].values()) and all(gate.get("outcome") == "done" and gate.get("evidence") for gate in gates.values())
    state.update(status="complete" if successful else "hard-stop", provider="codex", artifacts=graph.get("artifacts", {}))
    state["status"] = "fixture" if successful else "hard-stop"
    state["gates"] = gates
    state["teardown"] = {"provider": "codex", "evidence": gates.get("teardown", {}).get("evidence", [])} if successful else None
    state["retro"] = {"provider": "codex", "status": state["status"], "external_gates": "not executed; fixture only"}
    from runtime.graph import write_json
    write_json(args.state, state)
    print(json.dumps({"status": state["status"], "state": str(args.state)}))
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
