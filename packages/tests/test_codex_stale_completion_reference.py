"""A recorded completion stays valid after its child thread takes later successful turns."""

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

from packages.tests.codex_fixture import append, frozen_evals, read_json, spawn, state, transcripts, write_json


class StaleCompletionReferenceTests(unittest.TestCase):
    """Replay retained multi-turn child transcripts against a stored task_complete reference."""

    def setUp(self) -> None:
        """Record one done node whose child finished turn T1, then hold its transcript for follow-ups."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        self.addCleanup(patch.stopall)
        patch("pathlib.Path.home", return_value=directory).start()
        self.path = directory / "progress.json"
        write_json(self.path, state())
        write_json(self.path.with_name("evals.json"), frozen_evals())
        parent = transcripts(directory)
        graph.begin_wave(self.path)
        self.child = spawn(parent, read_json(self.path))
        self.first_turn = f"turn-{task_name('loop', 'U3[1]')}"
        envelope = {"wave_id": "wave-2", "results": {"U3[1]": {"outcome": "done", "evidence": "checked"}}}
        graph.record_wave(self.path, json.dumps(envelope))
        self.ticks = 3

    def _turn(self, turn_id: str, *terminals: str, start: bool = True) -> None:
        """Append one follow-up turn to the child thread: optional start, then each terminal event."""
        for event in ("task_started", *terminals) if start else terminals:
            self.ticks += 1
            payload = {"type": event, "turn_id": turn_id}
            append(
                self.child,
                {"timestamp": f"2026-09-21T00:00:{self.ticks:02d}Z", "type": "event_msg", "payload": payload},
            )

    def _stored(self) -> dict[str, Any]:
        return read_json(self.path)

    def _assert_rejected(self) -> None:
        with self.assertRaises(GraphError):
            validate_worker_evidence(self._stored())

    def test_completed_followup_after_record_keeps_earlier_completion_valid(self) -> None:
        """A successful follow-up turn does not invalidate the earlier recorded completion (fails on 795bb39c)."""
        validate_worker_evidence(self._stored())
        self._turn("followup", "task_complete")
        validate_worker_evidence(self._stored())
        self._turn("followup-2", "task_complete")
        validate_worker_evidence(self._stored())

    def test_unfinished_or_aborted_followup_still_rejects_the_earlier_completion(self) -> None:
        """Control: the worker's latest activity must still be a success; the gate is not loosened."""
        self._turn("followup")
        self._assert_rejected()
        self._turn("followup", "turn_aborted", start=False)
        self._assert_rejected()

    def test_forged_turn_ids_are_still_rejected_after_a_followup(self) -> None:
        """Control: only a task_complete this child actually started and finished can be referenced."""
        self._turn("followup", "task_complete")
        self._turn("aborted-turn", "turn_aborted")
        self._turn("tail", "task_complete")
        current = self._stored()
        stored = current["graph"]["nodes"]["U3[1]"]["evidence"][-1]
        for forged in ("turn-forged", "aborted-turn"):
            with self.subTest(forged=forged):
                stored["task_complete_turn_id"] = forged
                with self.assertRaises(GraphError):
                    validate_worker_evidence(current)
        stored["task_complete_turn_id"] = self.first_turn
        validate_worker_evidence(current)

    def test_completion_without_a_unique_start_is_rejected(self) -> None:
        """Control: an echoed task_complete lacking its own task_started never attests a turn."""
        self._turn("followup", "task_complete")
        self._turn(self.first_turn, "task_complete", start=False)
        self._assert_rejected()
        stray = self._stored()
        stray["graph"]["nodes"]["U3[1]"]["evidence"][-1]["task_complete_turn_id"] = "stray"
        self._turn("stray", "task_complete", start=False)
        with self.assertRaises(GraphError):
            validate_worker_evidence(stray)

    def test_completion_recorded_before_its_start_is_rejected(self) -> None:
        """Control: a turn whose task_complete precedes its own task_started never attests a completion."""
        self._turn("swapped", "task_complete", start=False)
        self._turn("swapped", start=True)
        self._turn("tail", "task_complete")
        swapped = self._stored()
        swapped["graph"]["nodes"]["U3[1]"]["evidence"][-1]["task_complete_turn_id"] = "swapped"
        with self.assertRaises(GraphError):
            validate_worker_evidence(swapped)

    def test_foreign_child_is_still_rejected_after_a_followup(self) -> None:
        """Control: child ownership is still checked before any turn is trusted."""
        self._turn("followup", "task_complete")
        text = self.child.read_text(encoding="utf-8")
        self.child.write_text(text.replace('"parent_thread_id": "parent"', '"parent_thread_id": "other"'))
        self._assert_rejected()


if __name__ == "__main__":
    unittest.main()
