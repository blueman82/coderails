"""A refused native spawn_agent is recordable as a failed attempt without weakening completion evidence."""

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
from graph_identity import GraphError, task_name

from packages.tests.codex_fixture import (
    append,
    frozen_evals,
    node,
    read_json,
    refuse,
    spawn,
    state,
    transcripts,
    write_json,
)

STALE: dict[str, object] = {"checked": True, "method": "native status", "result": "stalled"}


class RefusedSpawnTests(unittest.TestCase):
    """Replay retained parent transcripts in which one wave member's spawn_agent was refused."""

    def setUp(self) -> None:
        """Start a two-node wave over an isolated native session."""
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
        graph.begin_wave(self.path)

    def _record(self, second: str = "failed", **extra: dict[str, object]) -> dict[str, Any]:
        wave = read_json(self.path)["graph"]["active_wave"]["wave_id"]
        results: dict[str, Any] = {
            "U3[1]": {"outcome": "done", "evidence": "checked"},
            "U3[2]": {"outcome": second, "evidence": "checked", **extra},
        }
        return graph.record_wave(self.path, json.dumps({"wave_id": wave, "results": results}))

    def _rejected(self, second: str = "failed", **extra: dict[str, object]) -> None:
        before = self.path.read_bytes()
        with self.assertRaises(GraphError):
            self._record(second, **extra)
        self.assertEqual(self.path.read_bytes(), before)

    def _evidence(self, node_id: str) -> list[Any]:
        return list(read_json(self.path)["graph"]["nodes"][node_id]["evidence"])

    def test_refused_spawn_is_recorded_as_failed_and_the_node_retries(self) -> None:
        """One refused spawn no longer strands the wave: it fails, retries, and completes (fails on 795bb39c)."""
        spawn(self.parent, read_json(self.path), "U3[1]")
        refuse(self.parent, read_json(self.path), "U3[2]")
        self._record()
        current = read_json(self.path)
        self.assertEqual(current["graph"]["nodes"]["U3[2]"]["status"], "pending")
        self.assertEqual(current["graph"]["nodes"]["U3[2]"]["retry"]["attempts"], 1)
        wave = graph.begin_wave(self.path)
        self.assertEqual(wave["task_names"], {"U3[2]": task_name("loop", "U3[2]", 2)})
        spawn(self.parent, read_json(self.path), "U3[2]")
        graph.record_wave(
            self.path,
            json.dumps({"wave_id": wave["wave_id"], "results": {"U3[2]": {"outcome": "done", "evidence": "checked"}}}),
        )
        validate_worker_evidence(read_json(self.path))

    def test_repeated_refusals_bind_the_latest_call(self) -> None:
        """A transient refusal retried under the same task name may be refused again and still record."""
        spawn(self.parent, read_json(self.path), "U3[1]")
        refuse(self.parent, read_json(self.path), "U3[2]", "first")
        refuse(self.parent, read_json(self.path), "U3[2]", "second")
        self._record()
        self.assertEqual(self._evidence("U3[2]")[-1]["spawn_call_id"][:6], "second")

    def test_refusal_never_satisfies_a_completion(self) -> None:
        """Control: done, skipped and stale results still require an activity-backed child."""
        spawn(self.parent, read_json(self.path), "U3[1]")
        refuse(self.parent, read_json(self.path), "U3[2]")
        self._rejected(second="done")
        self._rejected(second="skipped")
        self._rejected(second="stale", stale_check=STALE)

    def test_failed_needs_a_real_refusal_row(self) -> None:
        """Control: a failed claim with no spawn call, an unanswered call, or a foreign task is rejected."""
        spawn(self.parent, read_json(self.path), "U3[1]")
        self._rejected()
        refuse(self.parent, read_json(self.path), "U3[1]")
        self._rejected()
        call = {
            "type": "function_call",
            "name": "spawn_agent",
            "namespace": "collaboration",
            "call_id": "unanswered",
            "arguments": json.dumps({"task_name": task_name("loop", "U3[2]", 1)}),
        }
        append(self.parent, {"type": "response_item", "payload": call})
        self._rejected()

    def test_wrong_attempt_refusal_is_rejected(self) -> None:
        """Control: a refusal of a different attempt's task name cannot stand in for this attempt."""
        spawn(self.parent, read_json(self.path), "U3[1]")
        future = read_json(self.path)
        future["graph"]["nodes"]["U3[2]"]["retry"]["attempts"] = 1
        refuse(self.parent, future, "U3[2]")
        self._rejected()

    def test_success_shaped_output_is_not_a_refusal(self) -> None:
        """A JSON-object spawn result with no activity row is not an error, so it cannot be recorded as refused."""
        spawn(self.parent, read_json(self.path), "U3[1]")
        refuse(self.parent, read_json(self.path), "U3[2]", result='{"agent_id": "abc"}')
        self._rejected()

    def test_validation_error_output_is_a_refusal(self) -> None:
        """Plain-text runtime errors other than the thread limit are error-shaped refusals."""
        spawn(self.parent, read_json(self.path), "U3[1]")
        refuse(self.parent, read_json(self.path), "U3[2]", result="agent_name must use only lowercase letters")
        self._record()
        self.assertEqual(read_json(self.path)["graph"]["nodes"]["U3[2]"]["evidence"][-1]["outcome"], "launch_refused")

    def test_activity_row_means_the_spawn_was_not_refused(self) -> None:
        """Control: an echoed SubAgentActivity for the call, even a mismatched one, voids the refusal claim."""
        spawn(self.parent, read_json(self.path), "U3[1]")
        call_id = refuse(self.parent, read_json(self.path), "U3[2]")
        item = {
            "type": "SubAgentActivity",
            "kind": "started",
            "id": call_id,
            "agent_thread_id": "x",
            "agent_path": "/y",
        }
        append(self.parent, {"type": "event_msg", "payload": {"item": item}})
        self._rejected()

    def test_stored_done_or_skipped_node_cannot_rest_on_a_refusal(self) -> None:
        """A hand-edited done/skipped node whose final attempt is a refusal fails revalidation (fails on f0e11666)."""
        spawn(self.parent, read_json(self.path), "U3[1]")
        refuse(self.parent, read_json(self.path), "U3[2]")
        self._record()
        stored = read_json(self.path)
        forged = stored["graph"]["nodes"]["U3[2]"]
        self.assertEqual(forged["evidence"][-1]["outcome"], "launch_refused")
        for status in ("done", "skipped"):
            for attempts in (0, 1):
                with self.subTest(status=status, attempts=attempts):
                    forged["status"], forged["retry"]["attempts"] = status, attempts
                    with self.assertRaises(GraphError):
                        validate_worker_evidence(stored)

    def test_stored_refusal_is_revalidated_against_the_transcript(self) -> None:
        """Control: tampering with, or removing, the parent rows behind a stored refusal fails revalidation."""
        spawn(self.parent, read_json(self.path), "U3[1]")
        refuse(self.parent, read_json(self.path), "U3[2]")
        elsewhere = refuse(self.parent, read_json(self.path), "U3[1]", "elsewhere")
        self._record()
        wave = graph.begin_wave(self.path)
        spawn(self.parent, read_json(self.path), "U3[2]")
        results = {"U3[2]": {"outcome": "done", "evidence": "checked"}}
        graph.record_wave(self.path, json.dumps({"wave_id": wave["wave_id"], "results": results}))
        validate_worker_evidence(read_json(self.path))
        stored = read_json(self.path)
        reference: dict[str, Any] = stored["graph"]["nodes"]["U3[2]"]["evidence"][1]
        self.assertEqual(reference["outcome"], "launch_refused")
        original = reference["spawn_call_id"]
        for forged in (stored["graph"]["nodes"]["U3[1]"]["evidence"][-1]["spawn_call_id"], elsewhere, "invented"):
            with self.subTest(call=forged):
                reference["spawn_call_id"] = forged
                with self.assertRaises(GraphError):
                    validate_worker_evidence(stored)
        reference["spawn_call_id"] = original
        rows = self.parent.read_text(encoding="utf-8").splitlines(keepends=True)
        self.parent.write_text("".join(row for row in rows if "refused" not in row), encoding="utf-8")
        with self.assertRaises(GraphError):
            validate_worker_evidence(stored)


if __name__ == "__main__":
    unittest.main()
