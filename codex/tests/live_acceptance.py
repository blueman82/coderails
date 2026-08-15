#!/usr/bin/env python3
"""Host-authenticated Codex graph acceptance; fixture tests stay elsewhere."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "codex"))
from hooks.lifecycle import validate  # noqa: E402
from runtime.graph import build_graph, execute  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--scenario", choices=("live", "failure", "missing", "refusal"), default="live")
    args = parser.parse_args()
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
