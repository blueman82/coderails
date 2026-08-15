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
    graph = build_graph()
    seen = []
    execute(graph, lambda node: seen.append(node) or "done")
    assert all(seen.index(edge["from"]) < seen.index(edge["to"]) for edge in graph["edges"])

    graph = build_graph(("A", "B"))
    attempts = {"SA": 0}
    def retry(node):
        attempts[node] = attempts.get(node, 0) + 1
        return "failed" if node == "SA" else "done"
    try:
        execute(graph, retry)
    except ValueError as error:
        assert "blocked" in str(error)
    assert attempts["SA"] == 5
    assert graph["nodes"]["SA"]["outcome"] == "hard-stop"
    assert graph["nodes"]["SB"]["outcome"] == "hard-stop"

    graph = build_graph(("A", "B"))
    calls = []
    execute(graph, lambda node: calls.append((node, graph["nodes"][node]["outcome"])) or "done")
    assert calls[:2] == [("SA", "pending"), ("SB", "pending")]

    hook = ROOT / "codex/hooks/lifecycle.py"
    valid = {"event": "complete", "state": {"status": "complete", "graph": graph, "retro": {}}}
    result = subprocess.run([sys.executable, str(hook)], input=json.dumps(valid), text=True, capture_output=True)
    assert result.returncode == 0, result.stdout
    invalid = {"event": "complete", "state": {"status": "complete", "graph": graph}}
    result = subprocess.run([sys.executable, str(hook)], input=json.dumps(invalid), text=True, capture_output=True)
    assert result.returncode == 1, result.stdout
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
