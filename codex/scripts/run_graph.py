#!/usr/bin/env python3
"""Run the native phase graph and persist its JSON state."""

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
    args = parser.parse_args()
    graph = build_graph()
    if args.state.exists():
        prior = json.loads(args.state.read_text(encoding="utf-8"))
        graph = prior["graph"]
    execute(graph)
    write_json(args.state, {"schema_version": 1, "status": "complete", "graph": graph})
    print(json.dumps({"status": "complete", "nodes": len(graph["nodes"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
