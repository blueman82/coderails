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
    state = Path(directory) / "state.json"
    contract = Path(directory) / "execution-graph.md"
    contract.write_text("""| ID | Node / true prerequisites | Ready when | Conditional skip or join |
|---|---|---|---|
| `root` | Stub state | ready | never |
| `review` | `root` | ready | never |
| `eval` | `root` | ready | never |
| `proof` | `root` | ready | never |
| `integrity` | `root` | ready | never |
| `wiki` | `root` | ready | never |
| `teardown` | `root` | ready | never |
""")
    run = {"run_id": "package-test-run", "revision": "0", "head": "package-test-head"}
    config = {"mode": "live", "run": run, "nodes": {}, "gates": {}}
    command = ["sh", "-c", "printf package"]
    nodes = ["root", "review", "eval", "proof", "integrity", "wiki", "teardown"]
    for node in nodes:
        config["nodes"][node] = {"command": command, "provider": "codex", "skill_id": "package." + node, "implementation_path": "runtime/graph.py"}
    for kind, node in zip(("review", "eval", "proof", "integrity", "wiki", "teardown"), nodes[1:]):
        artifact = Path(directory) / (kind + ".json")
        field, expected = {"review": ("review_status", "pass"), "eval": ("result", "GO"), "proof": ("result", "pass"), "integrity": ("integrity", "pass"), "wiki": ("result", "pass"), "teardown": ("result", "pass")} [kind]
        artifact.write_text(json.dumps({"schema_version": 1, "gate": kind, "provider": "codex", "run_id": run["run_id"], "revision": run["revision"], "head": run["head"], field: expected}))
        gate_command = ["sh", "-c", f"printf package-{kind}"]
        config["gates"][kind] = {"node": node, "command": gate_command, "provider": "codex", "skill_id": "package.gate." + kind, "implementation_path": "runtime/graph.py", "catalog_route": "graph-runtime", "catalog_kind": "runtime", "artifact": str(artifact), "artifact_path": str(artifact), "provenance": {"provider": "codex", "route": "package-route", **run}}
    implementations = Path(directory) / "implementations.json"
    implementations.write_text(json.dumps(config))
    subprocess.run([sys.executable, str(package / "scripts/run_graph.py"), "--contract", str(contract), "--implementations", str(implementations), "--state", str(state), "--catalog-root", str(package)], check=True)
    subprocess.run([sys.executable, str(package / "scripts/complete.py"), str(state)], check=True)
    completed = json.loads(state.read_text(encoding="utf-8"))
    assert completed["status"] == "complete" and completed["completed"] is True and completed["teardown"]["provider"] == "codex"
print("PASS")
