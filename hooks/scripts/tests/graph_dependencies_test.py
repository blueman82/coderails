"""Preserve predecessor, fanout and join release behavior using current graph IDs."""

from __future__ import annotations

import copy
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.graph_executor import ready_nodes
from hooks.scripts.tests.claude_graph_test_support import ROOT, GraphCase, dispatch, fixture, load, node


class DependencyTests(GraphCase):
    """Exercise native plan instruction paths separately from provider worker names."""

    def shape(
        self, identifiers: list[str], edges: list[tuple[str, str]], joins: dict[str, list[str]]
    ) -> dict[str, Any]:
        """Construct current registry nodes with explicit independent join state."""
        state = fixture.state(0)
        state["graph"]["nodes"] = {identifier: node(identifier) for identifier in identifiers}
        state["graph"]["edges"] = [{"from": source, "to": target} for source, target in edges]
        state["graph"]["joins"] = {
            key: {"id": key, "mode": "all", "inputs": inputs, "released": False} for key, inputs in joins.items()
        }
        return state

    def test_sequential_instruction_paths(self) -> None:
        """Build verification and wiki documentation links release only after their predecessor."""
        for first, second, source in (
            ("U3[1]", "U4[1]", "agents/loop-worker.md"),
            ("S9-wiki", "S9-docs", "agents/wiki-writer.md"),
        ):
            self.parent.write_text("")
            self.save(self.shape([first, second], [(first, second)], {}))
            self.assertEqual(ready_nodes(self.path), [first])
            plan = dispatch.plan(self.path)
            self.assertEqual(plan[0]["path"], source)
            self.assertFalse(plan[0]["unresolved"])
            self.assertNotIn("subagent_type", plan[0])
            self.finish()
            self.assertEqual(ready_nodes(self.path), [second])
            if second == "S9-docs":
                self.assertEqual(dispatch.plan(self.path)[0]["path"], "agents/docs-auditor.md")

    def test_join_fanout_symmetric_controls(self) -> None:
        """Both parallel results are required and join nodes are never native dispatches."""
        cases = (
            ("S2.5", "S2.6", "J2", "S2.7a"),
            ("S2.8", "S2.7e", "J2.8", "U3[1]"),
            ("U4b-merge-gate[1]", "U4b-merge-gate[2]", "J12-all-units", "S9-wiki"),
        )
        for first, second, join, downstream in cases:
            self.parent.write_text("")
            state = self.shape([first, second, join, downstream], [(join, downstream)], {join: [first, second]})
            self.save(state)
            self.assertEqual(set(ready_nodes(self.path)), {first, second})
            for finished in (first, second):
                partial = copy.deepcopy(state)
                partial["graph"]["nodes"][finished].update(status="done", outcome="done")
                self.save(partial)
                self.assertNotIn(join, ready_nodes(self.path))
                self.assertNotIn(downstream, ready_nodes(self.path))
            self.save(state)
            graph = self.opened()
            self.assertNotIn(join, graph["graph"]["active_wave"]["nodes"])
            for identifier in (first, second):
                fixture.spawn(self.parent, graph, identifier)
            result = dispatch.record_wave(self.path, fixture.report(graph))
            self.assertEqual(result["released_joins"], [join])
            self.assertEqual(ready_nodes(self.path), [downstream])
            self.assertTrue(load(self.path)["graph"]["joins"][join]["released"])

    def test_predecessor_status_and_readiness_cli(self) -> None:
        """Done/skipped succeed; pending/stale block; malformed persisted failures reject."""
        for status, expected in (
            ("done", "ready"),
            ("skipped", "ready"),
            ("pending", "blocked"),
            ("stale", "blocked"),
            ("failed", "blocked"),
        ):
            state = self.shape(["U3[1]", "U4[1]"], [("U3[1]", "U4[1]")], {})
            state["graph"]["nodes"]["U3[1]"].update(status=status, outcome=status)
            if status == "stale":
                state["graph"]["nodes"]["U3[1]"]["stale_check"] = {
                    "checked": True,
                    "method": "inspect",
                    "result": "idle",
                }
            self.save(state)
            before = self.path.read_bytes()
            result = subprocess.run(
                [sys.executable, str(ROOT / "hooks/scripts/lib/graph_readiness.py"), str(self.path), "U4[1]"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.stdout.strip(), expected)
            self.assertEqual(result.returncode, 0 if expected == "ready" else 1)
            self.assertEqual(before, self.path.read_bytes())

    def test_registry_resolution_and_shape_controls(self) -> None:
        """Unknown IDs/edges/cycles reject; a valid unmapped target is reported unresolved."""
        state = self.shape(["S2.5"], [], {})
        self.save(state)
        self.assertEqual(dispatch.plan(self.path)[0]["path"], "agents/design-scout.md")
        state["graph"]["nodes"]["S2.5"]["graph_role"] = "unknown-role"
        self.save(state)
        self.assertTrue(dispatch.plan(self.path)[0]["unresolved"])
        self.assertIsNone(dispatch.plan(self.path)[0]["path"])
        for edges in ([("U3[1]", "UNKNOWN")], [("U3[1]", "U3[1]")], [("U3[1]", "U4[1]"), ("U4[1]", "U3[1]")]):
            self.save(self.shape(["U3[1]", "U4[1]"], edges, {}))
            with self.assertRaises(ValueError):
                ready_nodes(self.path)
        state = fixture.state()
        state["graph"]["nodes"]["A"] = state["graph"]["nodes"].pop("U3[1]")
        self.save(state)
        with self.assertRaisesRegex(ValueError, "stable schema-v3"):
            dispatch.plan(self.path)

    def test_skill_readiness_call_is_in_graph_section(self) -> None:
        """Pin executable readiness guidance within its bounded dependency section."""
        text = (ROOT / "skills/agentic-loop/SKILL.md").read_text()
        section = text.split("The phases below are a dependency graph", 1)[1].split("### Phases -2 through 2.7", 1)[0]
        self.assertIn("graph_readiness.py", section)
        self.assertNotIn("Cluster wiki ingest", section)


if __name__ == "__main__":
    unittest.main()
