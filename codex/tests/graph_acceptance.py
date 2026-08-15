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
from runtime.graph import REQUIRED_GATES, build_graph, execute, ready  # noqa: E402

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
            graph_nodes = list(build_graph()["nodes"])
            config = {"mode": "fixture", "nodes": {
                node: {"command": local, "provider": "codex", "skill_id": f"fixture.{node}", "implementation_path": "codex/tests/graph_acceptance.py"}
                for node in graph_nodes
            }, "gates": {}}
            for kind, node in zip(REQUIRED_GATES, graph_nodes[:len(REQUIRED_GATES)]):
                config["gates"][kind] = {"node": node, "command": local, "provider": "codex", "skill_id": f"fixture.gate.{kind}", "implementation_path": "codex/tests/graph_acceptance.py"}
            implementations.write_text(json.dumps(config))
            command = [sys.executable, str(ROOT / "codex/scripts/run_graph.py"), "--state", str(state), "--implementations", str(implementations), "--contract", str(ROOT / "skills/agentic-loop/execution-graph.md")]
            first = subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertIn('"status": "fixture"', first.stdout)
            saved = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(saved["provider"], "codex")
            self.assertEqual(saved["status"], "fixture")
            self.assertEqual(saved["implementation"], "codex/runtime/graph.py")
            self.assertEqual(set(build_graph()["nodes"]), set(saved["graph"]["nodes"]))
            self.assertTrue(all(node["outcome"] in {"done", "skipped"} for node in saved["graph"]["nodes"].values()))
            before = state.read_text(encoding="utf-8")
            subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertEqual(before, state.read_text(encoding="utf-8"))

    def test_completion_teardown_and_index_negative_control(self) -> None:
        lifecycle = ROOT / "codex/hooks/lifecycle.py"
        graph = build_graph(("A",))
        execute(graph, {"SA": {"provider": "codex", "skill_id": "test.complete", "implementation_path": "codex/tests", "test_only": True, "outcome": "done"}})
        with tempfile.TemporaryDirectory() as directory:
            results = {"review": ("review_status", "pass"), "eval": ("result", "GO"), "proof": ("result", "pass"), "integrity": ("integrity", "pass"), "wiki": ("result", "pass"), "teardown": ("result", "pass")}
            gates = {}
            for kind, (field, expected) in results.items():
                artifact = Path(directory) / (kind + ".json")
                artifact.write_text(json.dumps({"schema_version": 1, "gate": kind, "provider": "codex", "run_id": "test", "revision": "0", "head": "test", field: expected}))
                gates[kind] = {"node": "SA", "outcome": "done", "evidence": [{"gate": kind, "provider": "codex", "artifact_path": str(artifact), "run_id": "test", "revision": "0", "head": "test"}]}
            good = {"event": "complete", "state": {"status": "complete", "graph": graph, "gates": gates, "teardown": {"provider": "codex", "evidence": [{"outcome": "done"}]}, "retro": {"provider": "codex", "status": "complete"}}}
            result = subprocess.run([sys.executable, str(lifecycle)], input=json.dumps(good), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout)
        bad = {"event": "complete", "state": {"status": "complete", "graph": graph}}
        result = subprocess.run([sys.executable, str(lifecycle)], input=json.dumps(bad), text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((ROOT / "skills/index.yaml").is_file())
        self.assertEqual(subprocess.run(["bash", str(ROOT / "scripts/validate-skills-index.sh")], capture_output=True).returncode, 0)

    def test_runner_missing_gate_configuration_is_non_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "progress.json"
            config = Path(directory) / "implementations.json"
            config.write_text(json.dumps({"nodes": {}, "gates": {}}))
            result = subprocess.run([
                sys.executable, str(ROOT / "codex/scripts/run_graph.py"),
                "--state", str(state), "--implementations", str(config),
                "--contract", str(ROOT / "skills/agentic-loop/execution-graph.md"),
            ], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            saved = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "hard-stop")
            self.assertFalse(any(node["outcome"] == "pending" for node in saved["graph"]["nodes"].values()))


if __name__ == "__main__":
    unittest.main()
