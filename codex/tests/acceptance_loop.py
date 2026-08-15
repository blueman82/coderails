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
from runtime.graph import build_graph, execute  # noqa: E402


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

    def persist(value: dict) -> None:
        print(json.dumps({"wave": [name for name, node in value["nodes"].items() if node["outcome"] != "pending"]}))

    execute(graph, implementations, state_path=args.state, persist=persist)
    state = json.loads(args.state.read_text(encoding="utf-8"))
    successful = all(node.get("outcome") in {"done", "skipped"} for node in graph["nodes"].values())
    state.update(status="complete" if successful else "hard-stop", provider="codex", artifacts=graph.get("artifacts", {}))
    state["retro"] = {"provider": "codex", "status": state["status"], "external_gates": "not executed; fixture only"}
    from runtime.graph import write_json
    write_json(args.state, state)
    print(json.dumps({"status": state["status"], "state": str(args.state)}))
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
