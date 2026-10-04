"""Codex copy of eval signing: freeze signs, graph_artifacts verifies, tamper and strip raise GraphError."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/codex/skills/agentic-loop/scripts"))
from graph_artifacts import validate_evals  # noqa: E402
from graph_identity import GraphError  # noqa: E402

CODEX_CLI = ROOT / "packages/codex/scripts/post_evals.py"


@unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen absent")
class CodexSigningTests(unittest.TestCase):
    """Drive the real Codex CLI, then the Codex reader."""

    def setUp(self) -> None:
        """Freeze and grade a signed loop suite under a throwaway keys dir."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.dict(os.environ, {"CODERAILS_KEYS_DIR": str(Path(self.tmp.name) / "keys")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.state = {"schema_version": 3, "session_id": "session", "loop_id": "loop", "revision": 2}
        directory = Path(self.tmp.name)
        (directory / "progress.json").write_text(json.dumps(self.state))
        self.path = directory / "evals.json"
        self.path.write_text(
            json.dumps(
                {
                    "scope": "loop",
                    "task_ref": "loop",
                    "head_sha": "head",
                    "verification_level": 1,
                    "verification_justification": "Codex signing",
                    "evals": [{"id": "E1", "priority": "P0", "mode": "agent-run", "status": "pass", "evidence": "x"}],
                    "amendments": [],
                }
            )
        )
        for operation in ("smoke-run", "grade-loop"):
            done = subprocess.run(
                [sys.executable, str(CODEX_CLI), operation, str(self.path)], capture_output=True, text=True, timeout=30
            )
            self.assertEqual(done.returncode, 0, done.stderr)

    def test_signed_suite_verifies(self) -> None:
        """Codex freeze signed; the reader accepts the graded suite."""
        document = json.loads(self.path.read_text())
        self.assertTrue(document["grading"]["signed"])
        validate_evals(self.state, 2, self.path)

    def test_corrupted_signature_is_refused(self) -> None:
        """A bad signature raises GraphError carrying signature_invalid."""
        document = json.loads(self.path.read_text())
        document["signature"]["payload"] = document["signature"]["payload"].replace("loop", "lop")
        self.path.write_text(json.dumps(document))
        with self.assertRaisesRegex(GraphError, "signature_invalid"):
            validate_evals(self.state, 2, self.path)

    def test_stripped_signature_is_refused(self) -> None:
        """Downgrade is detected through grading.signed, not accepted as legacy_unsigned."""
        document = json.loads(self.path.read_text())
        del document["signature"]
        self.path.write_text(json.dumps(document))
        with self.assertRaisesRegex(GraphError, "signature_missing"):
            validate_evals(self.state, 2, self.path)


if __name__ == "__main__":
    unittest.main()
