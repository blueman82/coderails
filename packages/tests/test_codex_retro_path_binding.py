"""Completion validates the same files that the assembled retrospective hashes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
from graph_identity import GraphError

from packages.tests.codex_completion_fixture import CompletionFixture, assemble_test_retro
from packages.tests.codex_fixture import complete, read_json, verify_completion, write_json


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
        aliases = [self.path.with_name(f"alias-{name}") for name in ("evals.json", "proof.json", "retro.json")]
        for alias, source in zip(aliases, (self.evals, self.proof, self.retro)):
            alias.symlink_to(source)
        verify_completion(self.path, "parent", aliases[0], aliases[1], aliases[2], self.transcript)
        wrong_alias = self.path.with_name("wrong-evals.json")
        wrong_alias.symlink_to(alternate)
        with self.assertRaisesRegex(GraphError, "evals.json path is not canonical"):
            verify_completion(self.path, "parent", wrong_alias, self.proof, self.retro, self.transcript)
