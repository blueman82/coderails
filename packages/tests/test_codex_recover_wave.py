"""Lease-bounded stall recovery reuses the stale/respawn path; it never bumps attempts without a stored reference."""

from __future__ import annotations

import contextlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/hooks/scripts"))
import graph
from graph_evidence import validate_worker_evidence
from graph_identity import GraphError
from graph_io import write as write_state

from packages.tests.codex_fixture import frozen_evals, node, read_json, spawn, state, transcripts, write_json

LAST_ACTIVITY = 1_789_948_802.0  # 2026-09-21T00:00:02Z, the fixture child's last record
LEASE = 600


class RecoverWaveTests(unittest.TestCase):
    """Drive begin-wave, a stalled worker, recover-wave, re-dispatch and record-wave end to end."""

    def setUp(self) -> None:
        """Setup."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.addCleanup(patch.stopall)
        patch("pathlib.Path.home", return_value=self.directory).start()
        self.path = self.directory / "progress.json"
        initial = state()
        initial["graph"]["nodes"]["U3[2]"] = node(2)
        write_json(self.path, initial)
        write_json(self.path.with_name("evals.json"), frozen_evals())
        self.parent = transcripts(self.directory)

    def _recover(self, now: float) -> dict[str, Any]:
        """Recover."""
        return graph.recover_wave(self.path, "parent", LEASE, now=now)

    def _spawn_all(self, terminal: bool = False) -> None:
        """Spawn all."""
        for unit in ("U3[1]", "U3[2]"):
            spawn(self.parent, read_json(self.path), unit, terminal=terminal)

    def test_all_stalled_nodes_are_recovered_then_redispatched_and_completed(self) -> None:
        """All stalled nodes are recovered then redispatched and completed."""
        graph.begin_wave(self.path)
        self._spawn_all()
        report = self._recover(LAST_ACTIVITY + LEASE)
        self.assertEqual({v["action"] for v in report["nodes"].values()}, {"stalled"})
        self.assertTrue(report["recovered"])
        recovered = read_json(self.path)
        self.assertIsNone(recovered["graph"]["active_wave"])
        self.assertEqual(recovered["graph"]["nodes"]["U3[1]"]["respawn"]["generation"], 1)
        self.assertEqual(recovered["graph"]["nodes"]["U3[1]"]["retry"]["attempts"], 0)
        wave = graph.begin_wave(self.path)
        self.assertTrue(all(name.endswith("_a2") for name in wave["task_names"].values()))
        self._spawn_all(terminal=True)
        results = {unit: {"outcome": "done", "evidence": "ok"} for unit in ("U3[1]", "U3[2]")}
        graph.record_wave(self.path, json.dumps({"wave_id": wave["wave_id"], "results": results}))
        validate_worker_evidence(read_json(self.path))

    def test_within_lease_is_reported_not_changed(self) -> None:
        """Within lease is reported not changed."""
        graph.begin_wave(self.path)
        self._spawn_all()
        before = self.path.read_text(encoding="utf-8")
        report = self._recover(LAST_ACTIVITY + LEASE - 1)
        self.assertEqual({v["action"] for v in report["nodes"].values()}, {"waiting"})
        self.assertFalse(report["recovered"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_undispatched_node_is_never_recorded_as_failed(self) -> None:
        """Undispatched node is never recorded as failed."""
        graph.begin_wave(self.path)
        spawn(self.parent, read_json(self.path), "U3[1]", terminal=False)
        before = self.path.read_text(encoding="utf-8")
        report = self._recover(LAST_ACTIVITY + LEASE)
        self.assertEqual(report["nodes"]["U3[2]"]["action"], "dispatch")
        self.assertFalse(report["recovered"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_mixed_wave_with_a_finished_worker_is_not_auto_recorded(self) -> None:
        """Mixed wave with a finished worker is not auto recorded."""
        graph.begin_wave(self.path)
        spawn(self.parent, read_json(self.path), "U3[1]", terminal=True)
        spawn(self.parent, read_json(self.path), "U3[2]", terminal=False)
        before = self.path.read_text(encoding="utf-8")
        report = self._recover(LAST_ACTIVITY + LEASE)
        self.assertEqual(report["nodes"]["U3[1]"]["action"], "record")
        self.assertFalse(report["recovered"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_summarize_names_the_phase_at_each_state(self) -> None:
        """Summarize names the phase at each state."""
        self.assertEqual(graph.summarize(self.path)["phase"], "ready to dispatch")
        graph.begin_wave(self.path)
        active = graph.summarize(self.path)
        self.assertEqual((active["phase"], active["active"]), ("waiting for worker", ["U3[1]", "U3[2]"]))
        self._spawn_all(terminal=True)
        results = {unit: {"outcome": "done", "evidence": "ok"} for unit in ("U3[1]", "U3[2]")}
        wave = read_json(self.path)["graph"]["active_wave"]["wave_id"]
        graph.record_wave(self.path, json.dumps({"wave_id": wave, "results": results}))
        finished = graph.summarize(self.path)
        self.assertEqual((finished["phase"], finished["done"]), ("ready to complete", ["U3[1]", "U3[2]"]))

    def test_wrong_session_is_refused(self) -> None:
        """Wrong session is refused."""
        graph.begin_wave(self.path)
        with self.assertRaises(GraphError):
            graph.recover_wave(self.path, "other", LEASE, now=LAST_ACTIVITY + LEASE)

    def _cycle(self) -> None:
        """Dispatch a wave, stall every worker, recover it."""
        graph.begin_wave(self.path)
        self._spawn_all()
        self.assertTrue(self._recover(LAST_ACTIVITY + LEASE)["recovered"])

    def test_recovery_is_bounded_by_the_retry_max(self) -> None:
        """Third recovery of a max-2 node is refused and changes nothing."""
        self._cycle()
        self._cycle()
        graph.begin_wave(self.path)
        self._spawn_all()
        before = self.path.read_text(encoding="utf-8")
        with self.assertRaisesRegex(GraphError, "recovery budget"):
            self._recover(LAST_ACTIVITY + LEASE)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_a_crash_after_the_first_save_never_strands_a_stale_node(self) -> None:
        """Recovery is one save: a second write that would crash is never reached, so no node is left stale."""
        graph.begin_wave(self.path)
        self._spawn_all()
        real, calls = write_state, list[int]()

        def flaky(path: Path, value: dict[str, Any]) -> None:
            if calls:
                raise OSError("crash between saves")
            calls.append(1)
            real(path, value)

        with patch("graph._write", side_effect=flaky), contextlib.suppress(GraphError):
            self._recover(LAST_ACTIVITY + LEASE)
        statuses = {n["status"] for n in read_json(self.path)["graph"]["nodes"].values()}
        self.assertNotIn("stale", statuses)

    def test_failing_save_leaves_state_unchanged(self) -> None:
        """A failing save leaves the wave active."""
        graph.begin_wave(self.path)
        self._spawn_all()
        before = self.path.read_text(encoding="utf-8")
        with patch("graph._write", side_effect=OSError("disk")), self.assertRaises(GraphError):
            self._recover(LAST_ACTIVITY + LEASE)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_second_recovery_of_the_same_wave_does_not_double_generation(self) -> None:
        """The competing call finds no active wave and refuses."""
        self._cycle()
        with self.assertRaisesRegex(GraphError, "no active wave"):
            self._recover(LAST_ACTIVITY + LEASE)
        self.assertEqual(read_json(self.path)["graph"]["nodes"]["U3[1]"]["respawn"]["generation"], 1)

    def test_empty_child_transcript_is_refused(self) -> None:
        """An unreadable child is a GraphError, not a crash."""
        graph.begin_wave(self.path)
        self._spawn_all()
        for child in self.parent.parent.glob("fixture-child-*.jsonl"):
            child.write_text("", encoding="utf-8")
        with self.assertRaises(GraphError):
            graph.recover_wave(self.path, "parent", LEASE, now=LAST_ACTIVITY + LEASE, apply=False)

    def test_child_without_timestamp_is_refused(self) -> None:
        """A timestamp-less last record is a GraphError, not a KeyError."""
        graph.begin_wave(self.path)
        self._spawn_all()
        for child in self.parent.parent.glob("fixture-child-*.jsonl"):
            lines = child.read_text(encoding="utf-8").splitlines()
            last = json.loads(lines[-1])
            del last["timestamp"]
            child.write_text("\n".join([*lines[:-1], json.dumps(last)]) + "\n", encoding="utf-8")
        with self.assertRaises(GraphError):
            self._recover(LAST_ACTIVITY + LEASE)

    def test_foreign_child_transcript_is_refused(self) -> None:
        """Ownership of the child is checked before the node is classified."""
        graph.begin_wave(self.path)
        self._spawn_all()
        for child in self.parent.parent.glob("fixture-child-*.jsonl"):
            text = child.read_text(encoding="utf-8").replace('"parent_thread_id": "parent"', '"parent_thread_id": "x"')
            child.write_text(text, encoding="utf-8")
        with self.assertRaises(GraphError):
            graph.recover_wave(self.path, "parent", LEASE, now=LAST_ACTIVITY + LEASE, apply=False)

    def _trace(self) -> list[dict[str, Any]]:
        """Read the sidecar trace."""
        trace = self.path.with_name("recovery-trace.jsonl")
        if not trace.exists():
            return []
        return [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]

    def test_recovery_writes_one_non_authoritative_trace_row_per_node(self) -> None:
        """Each recovered node leaves a closed-schema row carrying the stable reason code."""
        graph.begin_wave(self.path)
        self._spawn_all()
        report = self._recover(LAST_ACTIVITY + LEASE)
        self.assertEqual(report["reason_code"], "recovered")
        rows = self._trace()
        self.assertEqual([r["node_id"] for r in rows], ["U3[1]", "U3[2]"])
        for row in rows:
            self.assertEqual(
                set(row),
                {
                    "schema_version", "session_id", "loop_id", "wave_id", "node_id", "attempt", "revision",
                    "command", "outcome", "reason_code", "inputs_sha256",
                },
            )  # fmt: skip
            self.assertEqual((row["reason_code"], row["outcome"]), ("recovered", "recovered"))

    def test_trace_write_failure_fails_open(self) -> None:
        """An unwritable trace never alters or fails the transition."""
        self.path.with_name("recovery-trace.jsonl").mkdir()
        graph.begin_wave(self.path)
        self._spawn_all()
        report = self._recover(LAST_ACTIVITY + LEASE)
        self.assertTrue(report["recovered"])
        self.assertIsNone(read_json(self.path)["graph"]["active_wave"])

    def test_each_refusal_and_report_carries_a_distinct_code(self) -> None:
        """Foreign session, no wave, budget, finished worker and waiting worker each emit one code."""
        with self.assertRaises(GraphError) as no_wave:
            self._recover(LAST_ACTIVITY)
        self.assertEqual(getattr(no_wave.exception, "reason_code", None), "no_active_wave")
        graph.begin_wave(self.path)
        with self.assertRaises(GraphError) as foreign:
            graph.recover_wave(self.path, "other", LEASE, now=LAST_ACTIVITY)
        self.assertEqual(getattr(foreign.exception, "reason_code", None), "foreign_session")
        self.assertEqual(self._recover(LAST_ACTIVITY)["reason_code"], "no_spawn_dispatch")
        self._spawn_all()
        self.assertEqual(self._recover(LAST_ACTIVITY)["reason_code"], "worker_waiting")
        codes = [r["reason_code"] for r in self._trace()]
        self.assertEqual(codes[:2], ["no_active_wave", "foreign_session"])
        self.assertEqual(sorted(set(codes[2:])), ["no_spawn_dispatch", "worker_waiting"])

    def test_exhaustion_and_late_completion_codes(self) -> None:
        """A finished worker is reported for recording; an exhausted budget refuses with its own code."""
        graph.begin_wave(self.path)
        for unit in ("U3[1]", "U3[2]"):
            spawn(self.parent, read_json(self.path), unit, terminal=True)
        self.assertEqual(self._recover(LAST_ACTIVITY + LEASE)["reason_code"], "worker_finished_record")

    def test_budget_refusal_code(self) -> None:
        """The cap refusal is its own code."""
        self._cycle()
        self._cycle()
        graph.begin_wave(self.path)
        self._spawn_all()
        with self.assertRaises(GraphError) as refused:
            self._recover(LAST_ACTIVITY + LEASE)
        self.assertEqual(getattr(refused.exception, "reason_code", None), "recovery_budget_exhausted")
        self.assertEqual(self._trace()[-1]["reason_code"], "recovery_budget_exhausted")

    def test_unreadable_transcript_code(self) -> None:
        """An unreadable child refuses with its own code."""
        graph.begin_wave(self.path)
        self._spawn_all()
        for child in self.parent.parent.glob("fixture-child-*.jsonl"):
            child.write_text("", encoding="utf-8")
        with self.assertRaises(GraphError) as refused:
            self._recover(LAST_ACTIVITY + LEASE)
        self.assertEqual(getattr(refused.exception, "reason_code", None), "unreadable_transcript")


if __name__ == "__main__":
    unittest.main()
