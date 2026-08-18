#!/usr/bin/env python3
"""Run the native phase graph and persist its JSON state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from runtime.graph import (  # noqa: E402
    apply_work_unit_disposition,
    build_graph,
    codex_policy_mappings,
    execute,
    gate_snapshot,
    load_graph_policies,
    persist_parallel_review_join,
    prepare_implementations,
    read_json,
    StateConflict,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--implementations", type=Path, required=True, help="JSON node implementation records")
    parser.add_argument("--contract", type=Path, required=True, help="canonical execution-graph.md path")
    parser.add_argument("--work-units", type=Path, help="JSON array or object containing work_units")
    parser.add_argument("--catalog-root", type=Path, help="repository root used for Codex catalog route resolution")
    parser.add_argument("--index", type=Path, help="skills/index.yaml containing graph_policies")
    args = parser.parse_args()
    implementations = json.loads(args.implementations.read_text(encoding="utf-8"))
    work_units = None
    if args.work_units:
        value = json.loads(args.work_units.read_text(encoding="utf-8"))
        work_units = value.get("work_units", value) if isinstance(value, dict) else value
    catalog_root = args.catalog_root or Path(__file__).parents[2]
    policy_errors = []
    try:
        policies = load_graph_policies(args.index or catalog_root / "skills/index.yaml", repo_root=catalog_root)
    except (OSError, ValueError) as error:
        policies = {}
        policy_errors.append(f"graph_policies: {error}")
    graph = build_graph(contract_path=args.contract, work_units=work_units)
    graph["graph_policies"] = policies
    for policy in policies.values():
        join_node = str(policy["join"]["node"])
        join_node = join_node if join_node in graph["nodes"] else f"{join_node}[i]"
        for suffix in ("-claude[i]", "-codex[i]"):
            reviewer_node = f"{policy['node']}{suffix}"
            if reviewer_node in graph["nodes"]:
                graph["nodes"][reviewer_node]["dispatch"] = False
        if join_node in graph["nodes"]:
            graph["nodes"][join_node]["dispatch"] = False
    revision = 0
    if args.state.exists():
        prior = read_json(args.state)
        graph = prior["graph"]
        revision = prior.get("revision", 0)
    apply_work_unit_disposition(graph, work_units)
    mappings, configuration_errors = prepare_implementations(graph, implementations, catalog_root=catalog_root)
    if policies and not policy_errors:
        try:
            mappings.update(codex_policy_mappings(graph, policies, repo_root=catalog_root))
        except ValueError as error:
            policy_errors.append(str(error))
        for node, policy in policies.items() if implementations.get("mode", "live") != "fixture" else []:
            spec = implementations.get("parallel_review", {}).get(node) if isinstance(implementations, dict) and isinstance(implementations.get("parallel_review"), dict) else None
            if not isinstance(spec, dict):
                policy_errors.append(f"parallel-review {node}: missing evidence bundle")
                continue
            reviewers = spec.get("reviewers")
            run = spec.get("run")
            if not isinstance(reviewers, dict) or not isinstance(run, dict):
                policy_errors.append(f"parallel-review {node}: evidence bundle requires reviewers and run")
                continue
            try:
                persist_parallel_review_join(
                    graph,
                    policy,
                    Path(spec["canonical_input"]),
                    {"claude": Path(reviewers["claude"]), "codex": Path(reviewers["codex"])},
                    expected_run=run,
                    state_path=args.state,
                    expected_revision=revision,
                )
                revision = read_json(args.state).get("revision", revision)
            except (KeyError, OSError, TypeError, ValueError, StateConflict) as error:
                policy_errors.append(f"parallel-review {node}: {error}")
    configuration_errors = policy_errors + configuration_errors
    graph["configuration_errors"] = configuration_errors
    execute(graph, mappings if not configuration_errors else {}, state_path=args.state, expected_revision=revision, catalog_root=catalog_root)
    gates = gate_snapshot(graph, implementations)
    successful = not configuration_errors and all(node["outcome"] in {"done", "skipped"} for node in graph["nodes"].values()) and all(gate.get("outcome") in {"done", "skipped"} and gate.get("evidence") for gate in gates.values())
    mode = implementations.get("mode", "live") if isinstance(implementations, dict) else "live"
    status = "fixture" if mode == "fixture" and successful else ("complete" if successful else "hard-stop")
    teardown = {"provider": "codex", "gate": "teardown", "evidence": gates.get("teardown", {}).get("evidence", [])} if successful else None
    state = {
        "schema_version": 2,
        "status": status,
        "provider": "codex",
        "revision": graph.get("revision", revision),
        "implementation": "codex/runtime/graph.py",
        "gates": gates,
        "teardown": teardown,
        "retro": {"provider": "codex", "status": status, "external_gates": "not executed; fixture only" if mode == "fixture" else "configured Codex commands"},
        "graph": graph,
    }
    write_json(args.state, state, expected_revision=graph.get("revision", revision))
    print(json.dumps({"status": state["status"], "nodes": len(graph["nodes"])}))
    return 0 if status in {"complete", "fixture"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
