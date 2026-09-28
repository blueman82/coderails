"""Exercise workflow artifact parsing, trusted identity and neutral grading."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
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

    def test_all_marker_variants(self) -> None:
        """Preserve every marker grammar boundary from the retired shell suites."""
        for verdict in ("GO", "NO-GO"):
            for level in ("0", "1", "2"):
                line = eval_artifact.marker("123", "abc", verdict, level)
                self.assertEqual(
                    line,
                    f"<!-- coderails-eval-summary v1 pr=123 head_sha=abc result={verdict} "
                    f"verification_level={level} -->",
                )
                self.assertEqual(eval_artifact.parse_result(line), verdict)
                self.assertEqual(eval_artifact.parse_verification_level(line), level)
                self.assertTrue(eval_artifact.matches_marker(line, "123", "abc"))
                for pr, sha in (("999", "abc"), ("123", "wrong"), ("1|.*", "abc")):
                    self.assertFalse(eval_artifact.matches_marker(line, pr, sha))
                for invalid in (
                    line[:-4],
                    "junk " + line,
                    line + " junk",
                    line.replace("v1", "v2"),
                    line.replace(verdict, verdict.lower()),
                ):
                    self.assertFalse(eval_artifact.matches_marker(invalid, "123", "abc"))
                    self.assertEqual(eval_artifact.parse_result(invalid), "")
                    self.assertEqual(eval_artifact.parse_verification_level(invalid), "")
        literal = eval_artifact.marker("1|.*", "a.b", "GO", "1")
        self.assertTrue(eval_artifact.matches_marker(literal, "1|.*", "a.b"))
        self.assertFalse(eval_artifact.matches_marker(literal, "123", "a.b"))
        review = review_artifact.marker("123", "abc")
        self.assertEqual(review, "<!-- coderails-review-summary v1 pr=123 head_sha=abc -->")
        for pr, sha in (("999", "abc"), ("123", "wrong")):
            self.assertFalse(review_artifact.matches_marker(review, pr, sha))
        self.assertFalse(review_artifact.matches_marker(review[:-4], "123", "abc"))

    def test_priority_and_absent_eval_cases(self) -> None:
        """Only P0 status controls the verdict; invalid or absent arrays refuse."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evals.json"
            for text, expected in (
                ('{"evals":[]}', True),
                ("{}", False),
                ('{"evals":[{"priority":"P0","status":"pass"},{"priority":"P1","status":"fail"}]}', True),
                ('{"evals":[{"priority":"P0","status":"fail"},{"priority":"P1","status":"pass"}]}', False),
            ):
                path.write_text(text)
                self.assertEqual(eval_artifact.compute_go(path), expected)

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
