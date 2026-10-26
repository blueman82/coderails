"""Verify the Codex proof-results module's chained freeze and run frames."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

CODEX_ROOT = Path(__file__).resolve().parents[1] / "codex"
sys.path.insert(0, str(CODEX_ROOT))
from scripts.lib import proof_results as codex_proof_results  # noqa: E402


class CodexProofFrameTests(unittest.TestCase):
    """Exercise Codex package proof rows and their consumer verification."""

    def setUp(self) -> None:
        """Create an isolated proof document and results path."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.results = Path(temporary.name) / codex_proof_results.RESULTS_NAME
        self.state: dict[str, Any] = {"session_id": "codex-session", "loop_id": "codex-loop"}
        self.document: dict[str, Any] = {
            "schema_version": 2,
            "proofs": [{"id": "P1", "cmd": "printf ok", "expect": {"exit_code": 0}}],
        }

    def append_frames(self, cmd: str = "printf ok") -> None:
        """Append a freeze frame and an identity-bound satisfied run frame."""
        identity = self.state | {"started": "start", "ended": "end"}
        digest = codex_proof_results.doc_sha(self.document)
        codex_proof_results.append(self.results, kind="freeze", proof_json_sha256=digest, **identity)
        codex_proof_results.append(
            self.results,
            kind="run",
            proof_id="P1",
            cmd_sha256=codex_proof_results.sha(cmd),
            proof_json_sha256=digest,
            verdict="satisfied",
            expect_matched=True,
            cwd=str(Path.cwd()),
            head_sha=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            source_tree_sha=subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip(),
            **identity,
        )

    def test_valid_freeze_and_run_frames_verify(self) -> None:
        """A correctly bound freeze/run pair has a valid chain and satisfies the proof."""
        self.append_frames()

        rows = codex_proof_results.read_rows(self.results)
        self.assertEqual([row["kind"] for row in rows], ["freeze", "run"])
        self.assertEqual(rows[1]["prev_sha256"], rows[0]["row_sha256"])
        self.assertEqual(codex_proof_results.verify(self.document, self.results, self.state), ([], []))

    def test_tampered_and_wrong_bound_frames_are_rejected(self) -> None:
        """Edited bytes break the chain, while a re-chained wrong command hash fails proof binding."""
        self.append_frames()
        lines = self.results.read_text(encoding="utf-8").splitlines()
        lines[1] = lines[1].replace('"verdict": "satisfied"', '"verdict": "failed"')
        self.results.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(codex_proof_results.ChainError):
            codex_proof_results.read_rows(self.results)

        self.results.unlink()
        self.append_frames(cmd="printf wrong")
        offenders, _ = codex_proof_results.verify(self.document, self.results, self.state)
        self.assertEqual(offenders, ["P1(proof_stale_cmd)"])


if __name__ == "__main__":
    unittest.main()
