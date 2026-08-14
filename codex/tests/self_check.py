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

    hook = ROOT / "codex/hooks/lifecycle.py"
    valid = {"event": "complete", "state": {"status": "complete", "graph": graph, "retro": {}}}
    result = subprocess.run([sys.executable, str(hook)], input=json.dumps(valid), text=True, capture_output=True)
    assert result.returncode == 0, result.stdout
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
