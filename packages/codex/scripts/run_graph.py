#!/usr/bin/env python3
"""Run a JSON graph with a deterministic success handler and persist state."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from runtime.graph import execute, write_json  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--state", type=Path, required=True)
parser.add_argument("--graph", type=Path, required=True)
args = parser.parse_args()
graph = json.loads(args.graph.read_text(encoding="utf-8"))
execute(graph, lambda _node: "done")
write_json(args.state, {"schema_version": 1, "provider": "codex", "status": "complete", "graph": graph})
print(json.dumps({"status": "complete", "nodes": len(graph["nodes"])}))
