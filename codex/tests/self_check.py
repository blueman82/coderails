#!/usr/bin/env python3
"""Native smoke check for fan-out/join execution and lifecycle enforcement."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "codex"))
from runtime.graph import build_graph, execute  # noqa: E402


def main() -> int:
    graph = build_graph(("2", "2.5", "2.6", "2.7a"))
    seen = []
    execute(graph, lambda node: seen.append(node) or "done")
    assert seen.index("S2") < seen.index("S2.5")
    assert seen.index("S2.5") < seen.index("J2")
    assert seen.index("S2.6") < seen.index("J2")

    attempts = {"S2": 0}
    retry_graph = build_graph(("2",))
    retry_graph["nodes"]["S2"]["retry"]["max"] = 2
    def retry(node):
        attempts[node] = attempts.get(node, 0) + 1
        return "failed" if attempts[node] == 1 else "done"
    execute(retry_graph, retry)
    assert attempts["S2"] == 2

    hook = ROOT / "codex/hooks/lifecycle.py"
    valid = {"event": "complete", "state": {"status": "complete", "graph": graph, "retro": {}}}
    result = subprocess.run([sys.executable, str(hook)], input=json.dumps(valid), text=True, capture_output=True)
    assert result.returncode == 0, result.stdout
    missing = {"event": "complete", "state": {"status": "complete", "graph": graph}}
    assert subprocess.run([sys.executable, str(hook)], input=json.dumps(missing), text=True).returncode == 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
