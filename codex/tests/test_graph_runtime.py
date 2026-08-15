from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "codex"))

from runtime.graph import build_graph, execute, load_contract  # noqa: E402


PASS = [sys.executable, "-c", "print('ok')"]


class GraphRuntimeTests(unittest.TestCase):
    def test_loads_nodes_from_canonical_contract(self) -> None:
        nodes = load_contract(ROOT / "skills/agentic-loop/execution-graph.md")
        ids = {node["id"] for node in nodes}
        self.assertIn("S-2", ids)
        self.assertIn("S13-complete", ids)
        self.assertNotIn("PHASES", ids)

    def test_dispatches_independent_wave_then_join_and_persists(self) -> None:
        graph = build_graph(("P", "A", "B", "C"), joins={"C": ["A", "B"]})
        snapshots = []
        implementations = {
            node: {"command": PASS, "skill_id": f"skill-{node}", "path": f"codex/{node}.md"}
            for node in graph["nodes"]
        }
        execute(graph, implementations, persist=lambda value: snapshots.append(json.loads(json.dumps(value))))
        self.assertEqual(graph["nodes"]["C"]["outcome"], "done")
        self.assertTrue(all(snapshot["nodes"]["C"]["outcome"] == "pending" for snapshot in snapshots[:1]))
        self.assertGreaterEqual(len(snapshots), 3)

    def test_resume_retries_and_failure_are_durable(self) -> None:
        graph = build_graph(("A",))
        graph["nodes"]["SA"]["retry"]["max"] = 2
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "progress.json"
            outcomes = iter(["failed", "done"])
            execute(graph, {"SA": {"outcome": lambda: next(outcomes)}}, state_path=state)
            self.assertEqual(graph["nodes"]["SA"]["retry"]["attempts"], 2)
            resumed = json.loads(state.read_text())
            execute(resumed["graph"], {"SA": {"command": PASS}}, state_path=state)
            self.assertEqual(resumed["graph"]["nodes"]["SA"]["outcome"], "done")

        failed = build_graph(("A",))
        execute(failed, {"SA": {"outcome": "failed"}})
        self.assertEqual(failed["nodes"]["SA"]["outcome"], "hard-stop")

    def test_missing_implementation_and_gate_unavailability_fail_closed(self) -> None:
        graph = build_graph(("U4b-review",), joins={"U4b-review": []})
        execute(graph, {})
        node = graph["nodes"]["U4b-review"]
        self.assertEqual(node["outcome"], "hard-stop")
        self.assertIn("missing implementation", node["evidence"][-1]["output"])

    def test_completion_requires_all_nodes_done_or_skipped(self) -> None:
        graph = build_graph(("A", "B"))
        execute(graph, {"SA": {"command": PASS}, "SB": {"outcome": "skipped", "evidence": "not in scope"}})
        self.assertEqual({node["outcome"] for node in graph["nodes"].values()}, {"done", "skipped"})


if __name__ == "__main__":
    unittest.main()
