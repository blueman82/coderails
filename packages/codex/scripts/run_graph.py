#!/usr/bin/env python3
"""Run an installed Codex graph with an explicitly supplied contract and mappings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from runtime.graph import build_graph, execute, write_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--implementations", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args()
    implementations = json.loads(args.implementations.read_text(encoding="utf-8"))
    graph = build_graph(contract_path=args.contract)
    if args.state.exists():
        graph = json.loads(args.state.read_text(encoding="utf-8"))["graph"]
    execute(graph, implementations, state_path=args.state)
    successful = all(node.get("outcome") in {"done", "skipped"} for node in graph["nodes"].values())
    state = {"schema_version": 2, "status": "complete" if successful else "hard-stop", "provider": "codex", "graph": graph}
    write_json(args.state, state)
    print(json.dumps({"status": state["status"], "nodes": len(graph["nodes"])}))
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
