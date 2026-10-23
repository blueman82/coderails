"""FULL graph repair is conditional, recorded, bounded, and followed by fresh verification."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages/graph-semantics"))
import graph_repair  # noqa: E402
import graph_semantics  # noqa: E402
import graph_spec  # noqa: E402

from packages.tests.test_graph_spec import PROVIDERS, instantiate_loop  # noqa: E402


def failed_review(state: dict[str, Any]) -> dict[str, Any]:
    """Exercise the pure wave transition after a review reports a finding."""
    graph = state["graph"]
    for node in graph["nodes"].values():
        node.update(status="done", outcome="done")
    for join in graph["joins"].values():
        join["released"] = True
    for identifier in ("U4b-review[1]", "U6[1]", "U7/8[1]", "U4b-merge-gate[1]", "J12-all-units"):
        graph["nodes"][identifier].update(status="pending", outcome="pending")
    graph["joins"]["J12-all-units"]["released"] = False
    graph["nodes"]["U4b-review[1]"].update(status="running", outcome="running")
    graph["active_wave"] = {
        "wave_id": f"wave-{state['revision']}",
        "revision": state["revision"],
        "nodes": ["U4b-review[1]"],
    }
    proposal = graph_semantics.record_wave(
        state,
        graph["active_wave"]["wave_id"],
        {"U4b-review[1]": {"outcome": "failed", "evidence": "review finding"}},
    )
    graph_repair.apply_failed_gates(proposal, {"U4b-review[1]": {"outcome": "failed"}})
    return cast(dict[str, Any], proposal["state"])


class ConditionalRepairTests(unittest.TestCase):
    """Run each provider's record-repair command against a real stamped FULL graph."""

    def test_conditional_entries_are_guards(self) -> None:
        """Healthy FULL graphs have no automatically schedulable repair or respawn nodes."""
        spec, policy = graph_spec.load_spec(), graph_spec.load_policy()
        conditional = ("U5[1]", "U5-repair[1]", "U10-respawn[1]")
        for identifier in conditional:
            node = graph_spec.node_for(spec, identifier)
            if node is None:
                self.fail(f"missing spec node: {identifier}")
            self.assertEqual(node["kind"], "guard")
        nodes = graph_spec.expand(spec, policy, ["1"], "full")["nodes"]
        self.assertFalse(set(conditional) & set(nodes))

    def test_failed_review_blocks_until_a_distinct_repair_is_recorded(self) -> None:
        """The repair record can be an artifact update at the same commit SHA."""
        for name in PROVIDERS:
            with self.subTest(name), tempfile.TemporaryDirectory() as scratch:
                controller, _ = instantiate_loop(name, scratch, "full", "1")
                blocked = failed_review(controller.read())
                self.assertEqual(blocked["graph"]["nodes"]["U4b-review[1]"]["status"], "blocked")
                self.assertNotIn("U4b-review[1]", graph_semantics.ready(blocked))
                controller.path.write_text(json.dumps(blocked))
                args = [
                    "--session",
                    "sess-1",
                    "--unit",
                    "1",
                    "--failed-node",
                    "U4b-review[1]",
                    "--kind",
                    "artifact",
                    "--identity",
                    "comment-101",
                    "--diagnosis",
                    "missing review artifact",
                ]
                done = controller.run("record-repair", *args)
                self.assertEqual(done.returncode, 0, (name, done.stderr))
                repaired = controller.read()
                self.assertEqual(graph_semantics.ready(repaired), ["U4[1]"])
                self.assertEqual(repaired["graph"]["repair_attempts"]["1"][0]["identity"], "comment-101")
                self.assertEqual(repaired["graph"]["nodes"]["U4b-review[1]"]["status"], "pending")

    def test_duplicate_repair_identity_is_refused_without_a_write(self) -> None:
        """The same artifact cannot count as a second distinct repair attempt."""
        for name in PROVIDERS:
            with self.subTest(name), tempfile.TemporaryDirectory() as scratch:
                controller, _ = instantiate_loop(name, scratch, "full", "1")
                state = failed_review(controller.read())
                state["graph"]["repair_attempts"] = {
                    "1": [
                        {
                            "failed_node": "U4b-review[1]",
                            "kind": "artifact",
                            "identity": "comment-101",
                            "diagnosis": "first finding",
                            "revision": state["revision"] - 1,
                        },
                    ]
                }
                state["graph"]["nodes"]["U4b-review[1]"]["retry"]["attempts"] = 2
                controller.path.write_text(json.dumps(state))
                before = controller.path.read_bytes()
                result = controller.run(
                    "record-repair",
                    "--session",
                    "sess-1",
                    "--unit",
                    "1",
                    "--failed-node",
                    "U4b-review[1]",
                    "--kind",
                    "artifact",
                    "--identity",
                    "comment-101",
                    "--diagnosis",
                    "second finding",
                )
                self.assertEqual(result.returncode, 1, name)
                self.assertIn("repair_duplicate", result.stderr)
                self.assertEqual(controller.path.read_bytes(), before)

    def test_repair_rechecks_a_previously_skipped_downstream_gate(self) -> None:
        """A repaired artifact can change whether a former deployment skip applies."""
        for name in PROVIDERS:
            with self.subTest(name), tempfile.TemporaryDirectory() as scratch:
                controller, _ = instantiate_loop(name, scratch, "full", "1")
                state = failed_review(controller.read())
                state["graph"]["nodes"]["U7/8[1]"].update(status="skipped", outcome="skipped")
                controller.path.write_text(json.dumps(state))
                result = controller.run(
                    "record-repair",
                    "--session",
                    "sess-1",
                    "--unit",
                    "1",
                    "--failed-node",
                    "U4b-review[1]",
                    "--kind",
                    "source",
                    "--identity",
                    "a" * 40,
                    "--diagnosis",
                    "source changed",
                )
                self.assertEqual(result.returncode, 0, (name, result.stderr))
                self.assertEqual(controller.read()["graph"]["nodes"]["U7/8[1]"]["status"], "pending")

    def test_policy_repair_bound_hard_stops_the_next_failed_gate(self) -> None:
        """A tighter repair policy cannot strand a failed gate in blocked state."""
        with tempfile.TemporaryDirectory() as scratch:
            controller, _ = instantiate_loop("claude", scratch, "full", "1")
            state = failed_review(controller.read())
            state, _ = graph_repair.record_repair(
                state, "sess-1", "1", "U4b-review[1]", "artifact", "comment-101", "review fixed"
            )
            state["graph"]["nodes"]["U4b-review[1]"].update(status="running", outcome="running")
            state["graph"]["active_wave"] = {
                "wave_id": f"wave-{state['revision']}",
                "revision": state["revision"],
                "nodes": ["U4b-review[1]"],
            }
            policy = {**graph_spec.load_policy(), "repair_attempts_max": 1}
            with patch.object(graph_spec, "load_policy", return_value=policy):
                proposal = graph_semantics.record_wave(
                    state,
                    state["graph"]["active_wave"]["wave_id"],
                    {"U4b-review[1]": {"outcome": "failed", "evidence": "still failing"}},
                )
                graph_repair.apply_failed_gates(proposal, {"U4b-review[1]": {"outcome": "failed"}})
                result = proposal["state"]
            self.assertEqual(result["graph"]["nodes"]["U4b-review[1]"]["status"], "hard-stop")

    def test_malformed_repair_record_is_a_coded_refusal(self) -> None:
        """A JSON list in a typed field never escapes the provider loader as a traceback."""
        for name in PROVIDERS:
            with self.subTest(name), tempfile.TemporaryDirectory() as scratch:
                controller, _ = instantiate_loop(name, scratch, "full", "1")
                state = failed_review(controller.read())
                state["graph"]["repair_attempts"] = {
                    "1": [
                        {
                            "failed_node": ["U4b-review[1]"],
                            "kind": ["artifact"],
                            "identity": "comment-101",
                            "diagnosis": "review fixed",
                            "revision": state["revision"] - 1,
                        },
                    ]
                }
                controller.path.write_text(json.dumps(state))
                result = controller.run("inspect")
                self.assertEqual(result.returncode, 1, name)
                self.assertIn("repair_records_invalid", result.stderr)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
