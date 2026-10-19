"""Keep graph node names readable without changing their stable identities."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/graph-semantics"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages/codex/skills/agentic-loop/scripts"))

import graph_semantics  # noqa: E402

from packages.tests.provider_fixture import Provider  # noqa: E402


class GraphNodeNameTests(unittest.TestCase):
    """Check the shared node-name registry and both native graph CLIs."""

    def test_every_registered_node_has_a_one_word_name_and_keeps_its_id(self) -> None:
        """Every fixed and patterned schema-v3 node resolves without replacing its ID."""
        identifiers = set(graph_semantics.LABELS) | {
            "S2.7d[1]",
            "U3[1]",
            "U4[1]",
            "U4b-review[1]",
            "U5[1]",
            "U5-repair[1]",
            "U6[1]",
            "U7/8[1]",
            "U4b-merge-gate[1]",
            "U10-respawn[1]",
        }

        for identifier in identifiers:
            described = graph_semantics.describe_node(identifier)
            self.assertRegex(cast(str, described["job_name"]), r"^[A-Z][a-z]+$")
            self.assertIn(identifier, cast(str, described["display"]))

    def test_unit_nodes_show_the_human_lane_code(self) -> None:
        """The lane code is shown beside the existing machine node ID."""
        for node_id in ("S2.7d[15]", "U3[15]", "U4[15]", "U4b-review[15]"):
            with self.subTest(node_id=node_id):
                described = graph_semantics.describe_node(node_id)
                self.assertEqual(described["lane_code"], "C-3")
                display = cast(str, described["display"])
                self.assertIn("C-3", display)
                self.assertIn(node_id, display)

    def test_unknown_node_ids_are_rejected(self) -> None:
        """Names cannot be attached to arbitrary or legacy identifiers."""
        with self.assertRaises(graph_semantics.GraphSemanticError):
            graph_semantics.describe_node("C3")

    def test_dashboard_name_maps_match_between_provider_apps(self) -> None:
        """Provider dashboards use one identical display-name resolver."""
        claude = ROOT / "skills/dashboard/app/src/lib/collect/nodeDisplay.ts"
        codex = ROOT / "packages/codex/skills/dashboard/app/src/lib/collect/nodeDisplay.ts"
        self.assertEqual(claude.read_bytes(), codex.read_bytes())

    def test_provider_metadata_copies_match_the_canonical_source(self) -> None:
        """Both native providers use the exact same node-name registry."""
        source = ROOT / "packages/graph-semantics/node_metadata.py"
        for relative in (
            "skills/agentic-loop/scripts/node_metadata.py",
            "packages/codex/skills/agentic-loop/scripts/node_metadata.py",
        ):
            self.assertEqual(source.read_bytes(), (ROOT / relative).read_bytes(), relative)

    def test_both_provider_clis_expose_node_names_and_dispatch_names(self) -> None:
        """Inspect, summarize, and begin-wave retain IDs and add human-readable names."""
        with tempfile.TemporaryDirectory() as directory:
            providers = [Provider(Path(directory), name) for name in ("claude", "codex")]
            for provider in providers:
                inspected = provider.success("inspect")
                self.assertEqual(inspected["node_names"]["U3[1]"]["job_name"], "Builder")
                self.assertEqual(inspected["node_names"]["U3[1]"]["lane_code"], "A-1")

                summary = provider.success("summarize")
                self.assertEqual(summary["node_names"]["U3[1]"]["job_name"], "Builder")

                wave = provider.success("begin-wave")
                dispatches = wave.get("dispatches", [])
                if provider.name == "claude":
                    self.assertEqual(dispatches[0]["job_name"], "Builder")
                    self.assertEqual(dispatches[0]["lane_code"], "A-1")
                    self.assertEqual(
                        dispatches[0]["node_name_marker"], "CODERAILS_GRAPH_NODE_NAME=Builder · A-1 [U3[1]]"
                    )
                else:
                    self.assertEqual(wave["node_names"]["U3[1]"]["job_name"], "Builder")

    def test_claude_dispatch_prompt_keeps_ownership_first_and_adds_name_second(self) -> None:
        """The decorative marker follows the exact ownership envelope."""
        with tempfile.TemporaryDirectory() as directory:
            provider = Provider(Path(directory), "claude")
            wave = provider.success("begin-wave")
            dispatch = wave["dispatches"][0]
            self.assertTrue(dispatch["prompt_prefix"].startswith("CODERAILS_GRAPH_DISPATCH={"))
            self.assertEqual(dispatch["node_name_marker"], "CODERAILS_GRAPH_NODE_NAME=Builder · A-1 [U3[1]]")


if __name__ == "__main__":
    unittest.main()
