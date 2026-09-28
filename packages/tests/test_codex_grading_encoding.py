"""Keep native graph grading compatible with the neutral workflow checksum."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/codex/skills/agentic-loop/scripts"))
from graph_artifacts import validate_evals

ROOT = Path(__file__).resolve().parents[2]


class GradingEncodingTests(unittest.TestCase):
    """Use the real neutral CLI so both checksum implementations must agree."""

    def test_unicode_identity_survives_neutral_grading(self) -> None:
        """Valid Unicode eval IDs must not make a genuine neutral stamp unverifiable."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            state = {"schema_version": 3, "session_id": "session", "loop_id": "loop", "revision": 2}
            (directory / "progress.json").write_text(json.dumps(state))
            path = directory / "evals.json"
            path.write_text(
                json.dumps(
                    {
                        "scope": "loop",
                        "task_ref": "loop",
                        "head_sha": "head",
                        "verification_level": 1,
                        "verification_justification": "Native encoding parity",
                        "evals": [
                            {
                                "id": "preuve-é",
                                "priority": "P0",
                                "mode": "agent-run",
                                "status": "pass",
                                "evidence": "observed",
                            }
                        ],
                        "amendments": [],
                    }
                )
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/post_evals.py"), "grade-loop", str(path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "GO")
            validate_evals(state, 2, path)


if __name__ == "__main__":
    unittest.main()
