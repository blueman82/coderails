#!/usr/bin/env python3
"""Run an installed Codex graph with an explicitly supplied contract and mappings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from runtime.graph import apply_work_unit_disposition, build_graph, execute, gate_snapshot, prepare_implementations, read_json, write_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--implementations", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--work-units", type=Path)
    parser.add_argument("--catalog-root", type=Path)
    args = parser.parse_args()
    implementations = json.loads(args.implementations.read_text(encoding="utf-8"))
    work_units = None
    if args.work_units:
        value = json.loads(args.work_units.read_text(encoding="utf-8"))
        work_units = value.get("work_units", value) if isinstance(value, dict) else value
    graph = build_graph(contract_path=args.contract, work_units=work_units)
    revision = 0
    if args.state.exists():
        prior = read_json(args.state)
        graph, revision = prior["graph"], prior.get("revision", 0)
    apply_work_unit_disposition(graph, work_units)
    mappings, configuration_errors = prepare_implementations(graph, implementations, catalog_root=args.catalog_root)
    graph["configuration_errors"] = configuration_errors
    execute(graph, mappings if not configuration_errors else {}, state_path=args.state, expected_revision=revision)
    gates = gate_snapshot(graph, implementations)
    successful = not configuration_errors and all(node.get("outcome") in {"done", "skipped"} for node in graph["nodes"].values()) and all(gate.get("outcome") in {"done", "skipped"} and gate.get("evidence") for gate in gates.values())
    mode = implementations.get("mode", "live") if isinstance(implementations, dict) else "live"
    status = "fixture" if mode == "fixture" and successful else ("complete" if successful else "hard-stop")
    state = {"schema_version": 2, "status": status, "provider": "codex", "revision": graph.get("revision", revision), "gates": gates, "teardown": {"provider": "codex", "gate": "teardown", "evidence": gates.get("teardown", {}).get("evidence", [])} if successful else None, "retro": {"provider": "codex", "status": status, "external_gates": "not executed; fixture only" if mode == "fixture" else "configured Codex commands"}, "graph": graph}
    write_json(args.state, state, expected_revision=graph.get("revision", revision))
    print(json.dumps({"status": state["status"], "nodes": len(graph["nodes"])}))
    return 0 if status in {"complete", "fixture"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
