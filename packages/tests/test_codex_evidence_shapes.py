"""Preserve recursive evidence-shape, identifier reuse, and Unicode contracts."""

from __future__ import annotations

import copy
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
from graph_identity import GraphError, classify_worker_evidence

from packages.tests.codex_fixture import frozen_evals, node, read_json, spawn, state, transcripts, write_json


def encoded(value: object, depth: int = 4) -> str:
    """Repeatedly encode an adversarial evidence value."""
    result = json.dumps(value, ensure_ascii=False)
    for _ in range(depth - 1):
        result = json.dumps(result, ensure_ascii=False)
    return result


def attacks(reference: dict[str, Any]) -> list[object]:
    """Generate the former shell suite's recursive marker and identity attacks."""
    values: list[object] = [
        encoded(reference, 12),
        {"note": [[encoded({"inner": [encoded(reference)]})]]},
        {encoded(reference): "checked"},
        {encoded("spawn_call_id"): reference["spawn_call_id"]},
        encoded(f"  {json.dumps(reference)}  \n"),
    ]
    for token in (
        "kind",
        "attempt",
        "wave_id",
        "spawn_call_id",
        "agent_thread_id",
        "task_complete_turn_id",
        "codex_agent",
    ):
        values.extend((token, {"note": [encoded(token)]}))
    for key in ("spawn_call_id", "agent_thread_id", "task_complete_turn_id"):
        identifier = reference[key]
        values.extend((encoded({key: identifier}), identifier, {identifier: "ordinary"}, {"note": identifier}))
    return values


class EvidenceShapeTests(unittest.TestCase):
    """Check every evidence boundary rather than trusting caller-authored references."""

    def setUp(self) -> None:
        """Prepare a real completed worker plus a reusable active-state snapshot."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.addCleanup(patch.stopall)
        patch("pathlib.Path.home", return_value=self.directory).start()
        self.path = self.directory / "progress.json"
        write_json(self.path, state())
        write_json(self.path.with_name("evals.json"), frozen_evals())
        parent = transcripts(self.directory)
        graph.begin_wave(self.path)
        self.child = spawn(parent, read_json(self.path))
        self.active = read_json(self.path)
        self.record("checked")
        self.completed = read_json(self.path)
        self.reference = self.completed["graph"]["nodes"]["U3[1]"]["evidence"][-1]

    def record(self, evidence: object) -> None:
        """Record one caller-authored ordinary evidence value."""
        graph.record_wave(
            self.path,
            json.dumps({"wave_id": "wave-2", "results": {"U3[1]": {"outcome": "done", "evidence": evidence}}}),
        )

    def test_classifier_unicode_and_bounds(self) -> None:
        """Normalize fullwidth tokens but retain unrelated Unicode and input bounds."""
        classify = classify_worker_evidence
        for token in (
            "kind",
            "attempt",
            "wave_id",
            "spawn_call_id",
            "agent_thread_id",
            "task_complete_turn_id",
            "codex_agent",
        ):
            self.assertTrue(classify(token)[0])
            fullwidth = "".join(chr(ord(character) + 0xFEE0) for character in token)
            self.assertTrue(classify(fullwidth)[0])
            self.assertTrue(classify({"note": encoded(token)})[0])
        for ordinary in (
            "codеx_agent",
            "k💩nd",
            "sp💩wn_call_id",
            "w🌲ve_id",
            "agent_🧭hread_id",
            "codex_🐎gent",
            "γειά σου",
            {"ключ": "значение"},
            {"note": [encoded("checked", 12)]},
        ):
            self.assertEqual(classify(ordinary), (False, set()))
        with self.assertRaises(GraphError):
            classify("x" * ((1 << 20) + 1))
        repeated: list[object] = []
        with self.assertRaises(GraphError):
            classify([repeated, repeated])

    def test_record_rejects_every_shape_without_mutation(self) -> None:
        """Reject nested markers and current identities at the write boundary."""
        for attack in attacks(self.reference):
            with self.subTest(attack=attack):
                write_json(self.path, self.active)
                before = self.path.read_bytes()
                with self.assertRaises(ValueError):
                    self.record(attack)
                self.assertEqual(self.path.read_bytes(), before)

    def test_revalidation_rejects_every_shape(self) -> None:
        """Reject injected shapes in worker and join evidence on later validation."""
        for attack in attacks(self.reference):
            for location in ("U3[1]", "J12"):
                candidate = copy.deepcopy(self.completed)
                if location == "J12":
                    candidate["graph"]["joins"][location] = {"inputs": ["U3[1]"], "mode": "all", "released": True}
                    candidate["graph"]["nodes"][location] = node(status="done")
                candidate["graph"]["nodes"][location]["evidence"].append(attack)
                with self.assertRaises(GraphError):
                    validate_worker_evidence(candidate)

    def test_reference_shape_exact(self) -> None:
        """Reject partial, wrapped, Unicode-lookalike, and duplicated reference objects."""
        reference = self.reference
        invalid = [
            [reference],
            {"note": reference},
            reference | {"kind": "codex_agent "},
            {"spawn_call_id": reference["spawn_call_id"]},
            reference | {"kind": "codеx_agent"},
            encoded(reference),
        ]
        for value in invalid:
            candidate = copy.deepcopy(self.completed)
            candidate["graph"]["nodes"]["U3[1]"]["evidence"] = [value]
            with self.assertRaises(GraphError):
                validate_worker_evidence(candidate)
        duplicate = copy.deepcopy(self.completed)
        duplicate["graph"]["nodes"]["U3[2]"] = duplicate["graph"]["nodes"]["U3[1]"]
        with self.assertRaises(GraphError):
            validate_worker_evidence(duplicate)

    def test_duplicate_terminal_and_unicode_control(self) -> None:
        """A genuine Unicode result succeeds; a duplicated terminal fails."""
        for ordinary in ("k💩nd", "sp💩wn_call_id", "w🌲ve_id", "agent_🧭hread_id", "codex_🐎gent"):
            write_json(self.path, self.active)
            self.record(ordinary)
            validate_worker_evidence(read_json(self.path))
        lines = self.child.read_text(encoding="utf-8").splitlines()
        self.child.write_text("\n".join([*lines, lines[-1]]) + "\n", encoding="utf-8")
        write_json(self.path, self.active)
        with self.assertRaises(GraphError):
            self.record("checked")


if __name__ == "__main__":
    unittest.main()
