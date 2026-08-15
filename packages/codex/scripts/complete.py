#!/usr/bin/env python3
"""Add the completion marker only after the graph and teardown are valid."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from runtime.graph import write_json  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("state", type=Path)
args = parser.parse_args()
state = json.loads(args.state.read_text(encoding="utf-8"))
nodes = state.get("graph", {}).get("nodes", {})
if not nodes or any(node.get("outcome") not in {"done", "skipped"} for node in nodes.values()):
    raise SystemExit("completion refused: graph is not successful")
if not isinstance(state.get("teardown"), dict):
    raise SystemExit("completion refused: teardown is missing")
state.update(status="complete", completed=True)
write_json(args.state, state)
