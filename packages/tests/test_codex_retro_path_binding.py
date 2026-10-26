"""Completion validates the same files that the assembled retrospective hashes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
from graph_identity import GraphError

from packages.tests.codex_completion_fixture import CompletionFixture, assemble_test_retro
from packages.tests.codex_fixture import complete, read_json, write_json


class RetroPathBindingTests(CompletionFixture):
    """Caller file names cannot replace the retrospective's canonical sources."""

    def test_alternate_evals_and_proof_are_refused(self) -> None:
        """A passing alternate eval cannot hide a failing canonical suite."""
        original = self.evals.read_bytes()
        alternate = self.evals.with_name("alternate.json")
        alternate.write_bytes(original)
        write_json(self.evals, read_json(self.evals) | {"result": "NO-GO"})
        assemble_test_retro(self.path.parent, "parent")
        before = self.path.read_bytes()
        with self.assertRaisesRegex(GraphError, "evals.json path is not canonical"):
            complete(self.path, "parent", alternate, self.proof, self.retro, self.transcript)
        self.assertEqual(self.path.read_bytes(), before)

        self.evals.write_bytes(original)
        assemble_test_retro(self.path.parent, "parent")
        alternate_proof = self.proof.with_name("alternate-proof.json")
        alternate_proof.write_bytes(self.proof.read_bytes())
        with self.assertRaisesRegex(GraphError, "proof.json path is not canonical"):
            complete(self.path, "parent", self.evals, alternate_proof, self.retro, self.transcript)
        self.assertEqual(self.path.read_bytes(), before)
        complete(*self.arguments)
