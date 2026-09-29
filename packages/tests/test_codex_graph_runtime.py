"""Exercise current-schema graph transitions and native evidence fail-closed gates."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/hooks/scripts"))
import graph
import graph_semantics
from graph_completion import validate_work_units
from graph_evidence import validate_worker_evidence
from graph_identity import GraphError, task_name, task_node

from packages.tests.codex_fixture import frozen_evals, read_json, spawn, state, transcripts, write_json


class GraphRuntimeTests(unittest.TestCase):
    """Verify atomic transitions against real isolated native transcript fixtures."""

    def setUp(self) -> None:
        """Prepare an independent graph, eval suite, and native session."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.addCleanup(patch.stopall)
        patch("pathlib.Path.home", return_value=self.directory).start()
        self.path = self.directory / "progress.json"
        write_json(self.path, state())
        write_json(self.path.with_name("evals.json"), frozen_evals())
        self.parent = transcripts(self.directory)

    def record(self, outcome: str = "done", **extra: object) -> dict[str, Any]:
        """Record the active wave through the real adapter."""
        current = read_json(self.path)
        return graph.record_wave(
            self.path,
            json.dumps(
                {
                    "wave_id": current["graph"]["active_wave"]["wave_id"],
                    "results": {"U3[1]": {"outcome": outcome, "evidence": "checked", **extra}},
                }
            ),
        )

    def assert_unchanged(self, operation: Callable[..., object], *arguments: object, **keywords: object) -> None:
        """Assert a rejected mutation leaves bytes unchanged."""
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            operation(*arguments, **keywords)
        self.assertEqual(self.path.read_bytes(), before)

    def test_legacy_schema_rejected(self) -> None:
        """Reject historical state without migration or fallback."""
        current = state()
        for version in (1, 2, 4, None, True):
            current["schema_version"] = version
            write_json(self.path, current)
            self.assert_unchanged(graph.begin_wave, self.path)

    def test_frozen_evals_required_before_begin(self) -> None:
        """Missing or foreign frozen evals cannot create an active wave."""
        self.path.with_name("evals.json").unlink()
        self.assert_unchanged(graph.begin_wave, self.path)
        suite = frozen_evals()
        for field in ("session_id", "loop_id", "task_ref", "scope"):
            altered = suite | {field: "foreign"}
            write_json(self.path.with_name("evals.json"), altered)
            self.assert_unchanged(graph.begin_wave, self.path)

    def test_native_success_and_forged_evidence(self) -> None:
        """Bind real identity, reject omitted or caller-written provenance."""
        graph.begin_wave(self.path)
        self.assert_unchanged(self.record)
        spawn(self.parent, read_json(self.path))
        self.assert_unchanged(self.record, evidence="spawn_call_id")
        self.record()
        validate_worker_evidence(read_json(self.path))
        self.assertEqual(graph.inspect(self.path)["ready"], [])

    def test_retry_exhaustion(self) -> None:
        """Retry failures receive unique native identities and stop at the configured cap."""
        for attempt in (1, 2):
            wave = graph.begin_wave(self.path)
            self.assertEqual(wave["task_names"]["U3[1]"], task_name("loop", "U3[1]", attempt))
            spawn(self.parent, read_json(self.path))
            self.record("failed")
        current = read_json(self.path)
        self.assertEqual(current["graph"]["nodes"]["U3[1]"]["status"], "hard-stop")
        self.assert_unchanged(graph.begin_wave, self.path)

    def test_stale_unfinished_child_and_respawn(self) -> None:
        """Stale native ownership is valid without inventing a successful terminal."""
        graph.begin_wave(self.path)
        child = spawn(self.parent, read_json(self.path), terminal=False)
        self.record("stale", stale_check={"checked": True, "method": "native status", "result": "stalled"})
        graph.transition(self.path, "parent", "respawn_stale", "U3[1]", "checked stale child")
        wave = graph.begin_wave(self.path)
        self.assertEqual(wave["task_names"]["U3[1]"], task_name("loop", "U3[1]", 2))
        spawn(self.parent, read_json(self.path))
        self.record()
        validate_worker_evidence(read_json(self.path))
        records = child.read_text(encoding="utf-8")
        child.write_text(
            records.replace('"parent_thread_id": "parent"', '"parent_thread_id": "wrong"'), encoding="utf-8"
        )
        with self.assertRaises(GraphError):
            validate_worker_evidence(read_json(self.path))

    def test_fabricated_generation_rejected(self) -> None:
        """An inflated generation cannot substitute for a real prior native spawn."""
        current = state()
        current["graph"]["nodes"]["U3[1]"]["respawn"] = {"generation": 1, "intent": {"generation": 1, "reason": "fake"}}
        write_json(self.path, current)
        graph.begin_wave(self.path)
        spawn(self.parent, read_json(self.path))
        self.assert_unchanged(self.record)

    def test_work_units_independent(self) -> None:
        """Validate work units without mapping them onto graph nodes."""
        for units in (
            None,
            {},
            {"arbitrary": {"status": "done"}},
            {"other": {"status": "dropped", "dropped_reason": "scope"}},
        ):
            validate_work_units({"work_units": units})
        invalid: tuple[object, ...] = (
            [],
            "done",
            {"other": {}},
            {"other": {"status": "pending"}},
            {"other": {"status": "dropped", "dropped_reason": " "}},
        )
        for invalid_units in invalid:
            with self.assertRaises(GraphError):
                validate_work_units({"work_units": invalid_units})

    def test_task_attempt_roundtrip(self) -> None:
        """Native attempt identities remain canonical across decimal boundaries."""
        for attempt in (1, 2, 9, 10, 11, 99, 100):
            self.assertEqual(task_node(task_name("loop", "U3[1]", attempt)), ("loop", "U3[1]"))
        for suffix in ("_a1", "_a01", "_a0", "_a-1"):
            with self.assertRaises(GraphError):
                task_node(task_name("loop", "U3[1]") + suffix)

    def test_task_names_are_unique_across_loops(self) -> None:
        """The same node and attempt in separate loops have distinct native identities."""
        self.assertNotEqual(task_name("loop-a", "U3[1]"), task_name("loop-b", "U3[1]"))

    def test_dispatch_rejects_foreign_loop_task_identity(self) -> None:
        """A valid task identity from another loop cannot authorize this graph's dispatch."""
        graph.begin_wave(self.path)
        foreign_task = task_name("foreign-loop", "U3[1]")
        with self.assertRaises(GraphError):
            graph.authorize_dispatch(self.path, "parent", foreign_task, self.path.with_name("evals.json"))

    def test_exact_result_envelope(self) -> None:
        """Reject wrong wave, partial results, and malformed stale evidence atomically."""
        graph.begin_wave(self.path)
        spawn(self.parent, read_json(self.path))
        self.assert_unchanged(graph.record_wave, self.path, '{"wave_id":"wrong","results":{}}')
        self.assert_unchanged(self.record, "stale", stale_check={"checked": False})

    def test_transition_rejects_invalid_core_proposal_before_write(self) -> None:
        """The native boundary rejects a bad semantic proposal without replacing state."""
        graph.begin_wave(self.path)
        proposed = copy.deepcopy(read_json(self.path))
        proposed["revision"] += 1
        with patch.object(graph_semantics, "hard_stop", return_value={"state": proposed, "hard_stop": {}}):
            self.assert_unchanged(graph.transition, self.path, "parent", "hard_stop", "U3[1]", "owner decision")

    def test_hard_stop_writes_valid_singleton_result(self) -> None:
        """A successful native transition persists a complete schema-v3 graph."""
        graph.begin_wave(self.path)
        graph.transition(self.path, "parent", "hard_stop", "U3[1]", "owner decision")
        graph_semantics.validate(read_json(self.path))


if __name__ == "__main__":
    unittest.main()
