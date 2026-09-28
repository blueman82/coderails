"""Exercise workflow artifact parsing, trusted identity and neutral grading."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex"))
from scripts.lib import eval_artifact, review_artifact


class ArtifactTests(unittest.TestCase):
    """Reject spoofed markers and preserve canonical grading checksums."""

    def test_review_marker_requires_exact_literal_identity(self) -> None:
        """Require exact PR, SHA, version and line boundaries."""
        line = review_artifact.marker("12", "a.b")
        self.assertTrue(review_artifact.matches_marker(line, "12", "a.b"))
        for changed in ("x" + line, line + "x", line.replace("a.b", "axb"), line.replace("v1", "v2")):
            self.assertFalse(review_artifact.matches_marker(changed, "12", "a.b"))

    def test_eval_marker_grammar_is_closed(self) -> None:
        """Reject future versions, invalid levels, and invented verdicts."""
        line = eval_artifact.marker("12", "abc", "GO", "1")
        self.assertTrue(eval_artifact.matches_marker(line, "12", "abc"))
        self.assertEqual(eval_artifact.parse_result(line), "GO")
        self.assertEqual(eval_artifact.parse_verification_level(line), "1")
        for changed in (line + "x", line.replace("GO", "PASS"), line.replace("level=1", "level=3")):
            self.assertFalse(eval_artifact.matches_marker(changed, "12", "abc"))

    def test_go_and_checksum(self) -> None:
        """Bind statuses in array order, ignoring JSON formatting."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evals.json"
            path.write_text(json.dumps({"evals": [{"id": "E1", "priority": "P0", "status": "pass"}]}))
            self.assertTrue(eval_artifact.compute_go(path))
            canonical = '[{"id":"E1","priority":"P0","status":"pass"}]\nGO'
            self.assertEqual(eval_artifact.grading_checksum(path, "GO"), hashlib.sha256(canonical.encode()).hexdigest())
            path.write_text('{"evals": {}}')
            self.assertFalse(eval_artifact.compute_go(path))
            path.write_text("invalid")
            self.assertFalse(eval_artifact.compute_go(path))


if __name__ == "__main__":
    unittest.main()
