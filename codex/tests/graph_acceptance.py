#!/usr/bin/env python3
"""Independent Codex acceptance coverage for the durable graph contract."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "codex"))
from runtime.graph import PHASES, build_graph, execute, ready  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class CodexGraphAcceptance(unittest.TestCase):
    def test_readiness_and_a_or_b_join(self) -> None:
        graph = load("readiness.json")["graph"]
        self.assertTrue(ready(graph, "A"))
        self.assertTrue(ready(graph, "B"))
        self.assertFalse(ready(graph, "C"))
        graph["nodes"]["A"].update(status="done", outcome="done")
        self.assertFalse(ready(graph, "C"))
        graph["nodes"]["B"].update(status="done", outcome="done")
        self.assertTrue(ready(graph, "C"))

    def test_retry_stale_and_missing_implementation_are_fail_closed(self) -> None:
        graph = load("retry.json")["graph"]
        calls = []
        execute(graph, lambda node: calls.append(node) or ("failed" if len(calls) < 3 else "done"))
        self.assertEqual(calls, ["SA", "SA", "SA"])
        self.assertEqual(graph["nodes"]["SA"]["retry"]["attempts"], 3)

        graph = load("stale.json")["graph"]
        execute(graph, lambda _node: "stale")
        self.assertEqual(graph["nodes"]["SA"]["outcome"], "hard-stop")

        missing = load("missing_implementation.json")
        self.assertFalse((ROOT / missing["codex"]["path"]).is_file())

    def test_codex_dispatch_and_full_durable_run(self) -> None:
        self.assertNotIn("claude", str(Path(sys.modules["runtime.graph"].__file__)))
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "progress.json"
            implementations = Path(directory) / "implementations.json"
            local = [sys.executable, "-c", "print('fixture')"]
            implementations.write_text(json.dumps({
                node: {"command": local, "path": "codex/tests/graph_acceptance.py"}
                for node in build_graph()["nodes"]
            }))
            command = [sys.executable, str(ROOT / "codex/scripts/run_graph.py"), "--state", str(state), "--implementations", str(implementations)]
            first = subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertIn('"status": "complete"', first.stdout)
            saved = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(saved["provider"], "codex")
            self.assertEqual(saved["implementation"], "codex/runtime/graph.py")
            self.assertEqual(set(build_graph()["nodes"]), set(saved["graph"]["nodes"]))
            self.assertTrue(all(node["outcome"] in {"done", "skipped"} for node in saved["graph"]["nodes"].values()))
            before = state.read_text(encoding="utf-8")
            subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertEqual(before, state.read_text(encoding="utf-8"))

    def test_completion_teardown_and_index_negative_control(self) -> None:
        lifecycle = ROOT / "codex/hooks/lifecycle.py"
        graph = build_graph(("A",))
        execute(graph, {"SA": {"outcome": "done"}})
        good = {"event": "complete", "state": {"status": "complete", "graph": graph, "retro": {"provider": "codex"}}}
        result = subprocess.run([sys.executable, str(lifecycle)], input=json.dumps(good), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        bad = {"event": "complete", "state": {"status": "complete", "graph": graph}}
        result = subprocess.run([sys.executable, str(lifecycle)], input=json.dumps(bad), text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((ROOT / "skills/index.yaml").is_file())
        self.assertEqual(subprocess.run(["bash", str(ROOT / "scripts/validate-skills-index.sh")], capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
