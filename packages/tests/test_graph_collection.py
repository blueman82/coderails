"""List multiple native graphs with their registered human-readable node names."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PROVIDERS = (
    ROOT / "skills/agentic-loop/scripts/graph.py",
    ROOT / "packages/codex/skills/agentic-loop/scripts/graph.py",
)


class GraphCollectionTests(unittest.TestCase):
    """Exercise collection reads through both provider CLIs."""

    def setUp(self) -> None:
        """Create two isolated graph files beneath one collection root."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for loop_id in ("first", "second"):
            graph_state: dict[str, Any] = {
                "schema_version": 3,
                "session_id": "parent",
                "loop_id": loop_id,
                "revision": 1,
                "status": "in-progress",
                "graph": {
                    "nodes": {
                        "U3[1]": {
                            "label": "Build unit 1",
                            "status": "pending",
                            "outcome": "pending",
                            "retry": {"attempts": 0, "max": 2},
                            "respawn": {"generation": 0, "intent": None},
                            "evidence": [],
                        }
                    },
                    "edges": [],
                    "joins": {},
                    "active_wave": None,
                    "hard_stop": None,
                },
            }
            path = self.root / loop_id / "progress.json"
            path.parent.mkdir()
            path.write_text(json.dumps(graph_state), encoding="utf-8")

    def run_collection(self, script: Path) -> subprocess.CompletedProcess[str]:
        """Run the read-only command for one provider."""
        return subprocess.run(
            [sys.executable, str(script), "collection", str(self.root)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_both_providers_list_graphs_and_named_nodes_without_writes(self) -> None:
        """Collections are sorted, readable, and leave graph files unchanged."""
        before = {path: path.read_bytes() for path in self.root.rglob("progress.json")}
        for script in PROVIDERS:
            with self.subTest(provider=script.relative_to(ROOT)):
                result = self.run_collection(script)
                self.assertEqual(result.returncode, 0, result.stderr)
                graphs = json.loads(result.stdout)["graphs"]
                self.assertEqual([item["loop_id"] for item in graphs], ["first", "second"])
                self.assertEqual(
                    graphs[0]["nodes"],
                    [{"id": "U3[1]", "name": "Builder", "lane_code": "A-1", "status": "pending"}],
                )
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_explicit_links_and_disconnected_graph_are_returned_without_writes(self) -> None:
        """The collection index links graph records without changing native states."""
        (self.root / "collection.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "graphs": [
                        {"key": "first", "path": "first/progress.json", "loop_id": "first", "links": ["second"]},
                        {"key": "second", "path": "second/progress.json", "loop_id": "second", "links": []},
                    ],
                }
            ),
            encoding="utf-8",
        )
        before = {path: path.read_bytes() for path in self.root.rglob("progress.json")}
        for script in PROVIDERS:
            with self.subTest(provider=script.relative_to(ROOT)):
                result = self.run_collection(script)
                self.assertEqual(result.returncode, 0, result.stderr)
                graphs = json.loads(result.stdout)["graphs"]
                self.assertEqual(graphs[0]["links"], ["second"])
                self.assertEqual(graphs[1]["links"], [])
                self.assertEqual(json.loads(result.stdout)["unresolved_targets"], [])
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_missing_link_target_is_reported(self) -> None:
        """Unknown link keys fail clearly instead of producing guessed graph links."""
        (self.root / "collection.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "graphs": [
                        {"key": "first", "path": "first/progress.json", "loop_id": "first", "links": ["missing"]},
                        {"key": "second", "path": "second/progress.json", "loop_id": "second", "links": []},
                    ],
                }
            ),
            encoding="utf-8",
        )
        for script in PROVIDERS:
            with self.subTest(provider=script.relative_to(ROOT)):
                result = self.run_collection(script)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unknown graph link target 'missing'", result.stderr)

    def test_duplicate_collection_keys_are_refused(self) -> None:
        """Duplicate graph keys are ambiguous and rejected by both provider CLIs."""
        row: dict[str, Any] = {"key": "same", "path": "first/progress.json", "loop_id": "first", "links": []}
        (self.root / "collection.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "graphs": [row, {**row, "path": "second/progress.json", "loop_id": "second"}],
                }
            ),
            encoding="utf-8",
        )
        for script in PROVIDERS:
            with self.subTest(provider=script.relative_to(ROOT)):
                result = self.run_collection(script)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("duplicate graph key 'same'", result.stderr)

    def test_duplicate_collection_paths_are_refused(self) -> None:
        """One state file cannot be registered under two collection keys."""
        rows: list[dict[str, Any]] = [
            {"key": "one", "path": "first/progress.json", "loop_id": "first", "links": []},
            {"key": "two", "path": "first/progress.json", "loop_id": "first", "links": []},
        ]
        (self.root / "collection.json").write_text(
            json.dumps({"schema_version": 1, "graphs": rows}),
            encoding="utf-8",
        )
        for script in PROVIDERS:
            with self.subTest(provider=script.relative_to(ROOT)):
                result = self.run_collection(script)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("duplicate graph path 'first/progress.json'", result.stderr)

    def test_invalid_graph_refuses_collection(self) -> None:
        """Malformed graphs are reported as errors instead of disappearing."""
        (self.root / "broken").mkdir()
        (self.root / "broken/progress.json").write_text("{}", encoding="utf-8")
        for script in PROVIDERS:
            with self.subTest(provider=script.relative_to(ROOT)):
                result = self.run_collection(script)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("graph:", result.stderr)

    def test_symlinked_graph_outside_root_refuses_collection(self) -> None:
        """A symlink cannot make collection read graph state outside its root."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        outside = Path(temporary.name) / "progress.json"
        outside.write_text("{}", encoding="utf-8")
        (self.root / "external").mkdir()
        (self.root / "external/progress.json").symlink_to(outside)
        for script in PROVIDERS:
            with self.subTest(provider=script.relative_to(ROOT)):
                result = self.run_collection(script)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("escapes collection root", result.stderr)

    def test_symlinked_collection_index_outside_root_is_refused(self) -> None:
        """A collection index cannot make the command read outside its root."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        outside = Path(temporary.name) / "collection.json"
        outside.write_text(json.dumps({"schema_version": 1, "graphs": []}), encoding="utf-8")
        (self.root / "collection.json").symlink_to(outside)
        for script in PROVIDERS:
            with self.subTest(provider=script.relative_to(ROOT)):
                result = self.run_collection(script)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("collection index escapes collection root", result.stderr)


if __name__ == "__main__":
    unittest.main()
