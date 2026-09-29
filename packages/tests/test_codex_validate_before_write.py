"""Require Codex graph adapters to reject invalid core proposals before replacing state."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/hooks/scripts"))
import graph
import graph_semantics

from packages.tests.codex_fixture import frozen_evals, read_json, spawn, state, transcripts, write_json


class CodexValidateBeforeWriteTests(unittest.TestCase):
    """Exercise both provider transitions with malformed proposals at the write boundary."""

    def setUp(self) -> None:
        """Prepare isolated graph state, evals, and native transcripts."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.addCleanup(patch.stopall)
        patch("pathlib.Path.home", return_value=self.directory).start()
        self.path = self.directory / "progress.json"
        write_json(self.path, state())
        write_json(self.path.with_name("evals.json"), frozen_evals())
        self.parent = transcripts(self.directory)

    def test_begin_wave_rejects_invalid_core_proposal_without_writing(self) -> None:
        """Reject an invalid proposed wave before changing progress bytes."""
        original = graph_semantics.begin_wave

        def invalid_proposal(current: dict[str, Any]) -> dict[str, Any]:
            proposal = original(current)
            proposal["state"]["schema_version"] = 2
            return proposal

        before = self.path.read_bytes()
        with patch.object(graph_semantics, "begin_wave", side_effect=invalid_proposal), self.assertRaises(ValueError):
            graph.begin_wave(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_record_wave_rejects_invalid_core_proposal_without_writing(self) -> None:
        """Reject an invalid recorded wave before changing progress bytes."""
        graph.begin_wave(self.path)
        spawn(self.parent, read_json(self.path))
        state_before = read_json(self.path)
        raw_results = json.dumps(
            {
                "wave_id": state_before["graph"]["active_wave"]["wave_id"],
                "results": {"U3[1]": {"outcome": "done", "evidence": "checked"}},
            }
        )
        original = graph_semantics.record_wave

        def invalid_proposal(current: dict[str, Any], wave_id: object, results: object) -> dict[str, Any]:
            proposal = original(current, wave_id, results)
            proposal["state"]["schema_version"] = 2
            return proposal

        before = self.path.read_bytes()
        with patch.object(graph_semantics, "record_wave", side_effect=invalid_proposal), self.assertRaises(ValueError):
            graph.record_wave(self.path, raw_results)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
