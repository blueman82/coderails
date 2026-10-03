"""Lease-bounded stall recovery reuses the stale/respawn path; it never bumps attempts without a stored reference."""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
