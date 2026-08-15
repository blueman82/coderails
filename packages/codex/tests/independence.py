#!/usr/bin/env python3
"""Copy-package smoke test: imports and execution must use package-local paths."""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
forbidden = "cl" + "aude"
assert not any(forbidden in path.read_text(encoding="utf-8").lower() for path in ROOT.rglob("*") if path.is_file())
with tempfile.TemporaryDirectory() as directory:
    package = Path(directory) / "package"
    shutil.copytree(ROOT, package)
    graph = Path(directory) / "graph.json"
    state = Path(directory) / "state.json"
    graph.write_text(json.dumps({"nodes": {"one": {"outcome": "pending", "retry": {"max": 1}}}, "edges": [], "joins": {}}))
    subprocess.run([sys.executable, str(package / "scripts/run_graph.py"), "--graph", str(graph), "--state", str(state)], check=True)
    subprocess.run([sys.executable, str(package / "scripts/teardown.py"), str(state)], check=True)
    subprocess.run([sys.executable, str(package / "scripts/complete.py"), str(state)], check=True)
    completed = json.loads(state.read_text(encoding="utf-8"))
    assert completed["completed"] is True and completed["teardown"]["provider"] == "codex"
print("PASS")
