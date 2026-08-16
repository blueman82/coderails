#!/usr/bin/env python3
"""Host-authenticated Codex graph acceptance; fixture tests stay elsewhere."""

from __future__ import annotations

import argparse
import json
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "codex"))
from hooks.lifecycle import validate  # noqa: E402
from runtime.graph import REQUIRED_GATES, apply_work_unit_disposition, build_graph, execute, gate_snapshot, prepare_implementations, write_json  # noqa: E402


def canonical_config(state: Path) -> tuple[dict, dict, dict]:
    run = {"run_id": f"codex-{state.stem}", "revision": "1", "head": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()}
    graph = build_graph()
    apply_work_unit_disposition(graph, None)
    for node, record in graph["nodes"].items():
        if not record.get("dispatch", True) and record["outcome"] == "pending":
            record.update(status="skipped", outcome="skipped")
    for kind in REQUIRED_GATES:
        node = f"E3-gate-{kind}"
        graph["nodes"][node] = {"status": "pending", "outcome": "pending", "retry": {"attempts": 0, "max": 1}, "name": node, "dispatch": True}
        graph["edges"].append({"from": "S13-complete", "to": node})
    artifacts = state.parent / "artifacts"
    config = {"mode": "live", "run": run, "nodes": {}, "gates": {}}
    for node in graph["nodes"]:
        if graph["nodes"][node]["outcome"] == "skipped":
            continue
        config["nodes"][node] = {
            "adapter": "codex-exec",
            "prompt": f"Complete canonical graph node {node}; report PHASE_{node}_OK. Do not edit files or run additional commands.",
            "cwd": str(ROOT),
            "provider": "codex",
            "skill_id": f"canonical.{node}",
            "implementation_path": "codex/runtime/codex_exec.py",
        }
    for kind in REQUIRED_GATES:
        node = f"E3-gate-{kind}"
        artifact = artifacts / f"{kind}.json"
        raw = artifacts / f"{kind}.raw.jsonl"
        command = [sys.executable, str(ROOT / "codex/runtime/gate_producer.py"), "--gate", kind, "--artifact", str(artifact), "--raw", str(raw), "--run-id", run["run_id"], "--revision", run["revision"], "--head", run["head"], "--cwd", str(ROOT)]
        if kind == "teardown":
            command += ["--retro", str(state.parent / "retro.json")]
        config["nodes"][node] = {"command": command, "provider": "codex", "skill_id": f"canonical.gate.{kind}", "implementation_path": "codex/runtime/gate_producer.py"}
        config["gates"][kind] = {"node": node, "gate": kind, "command": command, "provider": "codex", "skill_id": f"canonical.gate.{kind}", "implementation_path": "codex/runtime/gate_producer.py", "artifact_path": str(artifact), "provenance": {"provider": "codex", "route": "codex-exec", **run}}
    return graph, config, run


def run_canonical(state: Path, *, invoke=None) -> int:
    if state.exists():
        saved = json.loads(state.read_text(encoding="utf-8"))
        if saved.get("status") == "complete":
            allowed, _ = validate({"event": "complete", "state": saved})
            return 0 if allowed else 1
    graph, config, run = canonical_config(state)
    if invoke is not None:
        import runtime.graph as graph_module
        original = graph_module.codex_exec
        graph_module.codex_exec = invoke
    try:
        mappings, errors = prepare_implementations(graph, config, catalog_root=ROOT)
        if errors:
            raise RuntimeError("canonical configuration invalid: " + "; ".join(errors))
        execute(graph, mappings, state_path=state, catalog_root=ROOT)
    finally:
        if invoke is not None:
            graph_module.codex_exec = original
    gates = gate_snapshot(graph, config)
    retro_path = state.parent / "retro.json"
    state_value = {"schema_version": 2, "status": "complete", "provider": "codex", "run": run, "revision": graph.get("revision", 0), "gates": gates, "teardown": {"provider": "codex", "gate": "teardown", "outcome": "done", "evidence": gates["teardown"]["evidence"]}, "retro": json.loads(retro_path.read_text(encoding="utf-8")) if retro_path.exists() else {}, "graph": graph}
    allowed, reason = validate({"event": "complete", "state": state_value})
    state_value["status"] = "complete" if allowed else "hard-stop"
    write_json(state, state_value, expected_revision=graph.get("revision", 0))
    print(json.dumps({"status": state_value["status"], "state": str(state), "artifacts": {kind: str(state.parent / "artifacts" / f"{kind}.json") for kind in REQUIRED_GATES}, "lifecycle": reason}))
    return 0 if allowed else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--scenario", choices=("live", "failure", "missing", "refusal", "canonical"), default="live")
    parser.add_argument("--canonical", action="store_true")
    args = parser.parse_args()
    if args.canonical or args.scenario == "canonical":
        return run_canonical(args.state)
    revision = 0
    if args.scenario == "live" and args.state.exists():
        saved = json.loads(args.state.read_text(encoding="utf-8"))
        graph = saved["graph"]
        revision = saved.get("revision", 0)
    else:
        graph = build_graph(("A", "B", "C"), joins={"C": ("A", "B")}, edges=(("A", "C"), ("B", "C")))
    prompt = "Return exactly LIVE_GRAPH_NODE_OK. Do not edit files or run additional commands."
    implementations = {
        name: {"adapter": "codex-exec", "prompt": prompt, "cwd": str(ROOT), "provider": "codex", "skill_id": "live." + name, "implementation_path": "codex/runtime/codex_exec.py"}
        for name in graph["nodes"]
    }
    if args.scenario == "failure":
        implementations["A"]["cwd"] = str(args.state.parent / "missing-worktree")
    if args.scenario == "missing":
        del implementations["B"]
    if args.scenario == "refusal":
        event = {"event": "complete", "state": {"status": "complete", "graph": {"nodes": {"A": {"outcome": "done"}}}}}
        allowed, reason = validate(event)
        print(json.dumps({"allowed": allowed, "reason": reason, "evidence": "gate refusal"}))
        return 0 if not allowed else 1
    execute(graph, implementations, state_path=args.state, expected_revision=revision)
    print(json.dumps({"scenario": args.scenario, "state": str(args.state), "nodes": graph["nodes"]}, default=str))
    return 0 if all(node["outcome"] == "done" for node in graph["nodes"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
