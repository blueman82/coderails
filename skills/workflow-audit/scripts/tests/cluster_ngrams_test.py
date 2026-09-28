"""Preserve repeated n-gram support, ranking, type boundaries and malformed-line isolation."""

import json
import tempfile
import unittest
from pathlib import Path

from audit_test_support import FIXTURES, invoke


class ClusterTests(unittest.TestCase):
    """Use hand-computed windows and actual CLI output as independent assertions."""

    def test_known_counts_threshold_ranking_and_top(self) -> None:
        """Count occurrences separately from support and deterministically rank ties."""
        source = (FIXTURES / "cluster-3sessions.jsonl").read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = invoke("cluster_ngrams", root, stdin=source)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(value["scanned_sessions"], 4)
            self.assertEqual(
                value["clusters"][0],
                {
                    "ngram": ["Bash:git log", "Bash:git push", "Skill:prime"],
                    "n": 3,
                    "count": 3,
                    "sessions": [f"{digit * 8}-{digit * 4}-{digit * 4}-{digit * 4}-{digit * 12}" for digit in "123"],
                },
            )
            self.assertEqual([cluster["count"] for cluster in value["clusters"]], [3, 3, 3])
            self.assertGreaterEqual(value["diagnostics"]["below_threshold"], 1)
            self.assertFalse(value["diagnostics"]["truncated"])
            self.assertEqual(invoke("cluster_ngrams", root, stdin=source).stdout, result.stdout)
            for top in ("0", "1"):
                capped = json.loads(invoke("cluster_ngrams", root, "--top", top, stdin=source).stdout)
                self.assertEqual(len(capped["clusters"]), 1)
                self.assertTrue(capped["diagnostics"]["truncated"])
            self.assertEqual(
                json.loads(invoke("cluster_ngrams", root, "--min-sessions", "4", stdin=source).stdout)["clusters"], []
            )

    def test_occurrences_do_not_inflate_distinct_support(self) -> None:
        """Duplicate session lines cannot satisfy support while repeated windows count."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            single = {"session_id": "dup1", "events": [{"tool": "A"}, {"tool": "B"}]}
            second = dict(single, session_id="dup2")
            source = "\n".join(json.dumps(row) for row in [single, single, second])
            self.assertEqual(json.loads(invoke("cluster_ngrams", root, stdin=source).stdout)["clusters"], [])
            repeated = dict(single, session_id="rep1", events=[{"tool": tool} for tool in "ABAB"])
            source = "\n".join(
                json.dumps(row) for row in [repeated, dict(single, session_id="rep2"), dict(single, session_id="rep3")]
            )
            value = json.loads(invoke("cluster_ngrams", root, stdin=source).stdout)
            self.assertEqual(
                value["clusters"], [{"ngram": ["A", "B"], "n": 2, "count": 4, "sessions": ["rep1", "rep2", "rep3"]}]
            )

    def test_malformed_nonobjects_and_structured_fields(self) -> None:
        """Reject invalid records by line and never serialize private object fields."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = (FIXTURES / "cluster-3sessions.jsonl").read_text()
            result = invoke("cluster_ngrams", root, stdin="{bad\n" + source)
            self.assertIn("jq_parse_error:1", result.stderr)
            self.assertEqual(json.loads(result.stdout)["scanned_sessions"], 4)
            self.assertEqual(json.loads(result.stdout)["clusters"][0]["count"], 3)
            result = invoke("cluster_ngrams", root, stdin='false\n0\n"x"\n[1,2,3]\nnull\n')
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["scanned_sessions"], 0)
            self.assertEqual(result.stderr.splitlines(), [f"jq_parse_error:{index}" for index in range(1, 6)])
            source = "\n".join(
                json.dumps(
                    {
                        "session_id": str(index),
                        "events": [
                            {"tool": "Bash", "head": {"private": "never leak"}},
                            {"tool": 123, "head": "x"},
                            {"tool": "Read"},
                        ],
                    }
                )
                for index in range(3)
            )
            result = invoke("cluster_ngrams", root, stdin=source)
            self.assertEqual(result.returncode, 0)
            self.assertNotIn("never leak", result.stdout)
            self.assertNotIn('":x"', result.stdout)
            self.assertEqual(result.stderr, "")
            help_result = invoke("cluster_ngrams", root, "--help")
            self.assertEqual(help_result.returncode, 0)
            self.assertIn("min-sessions", help_result.stdout)


if __name__ == "__main__":
    unittest.main()
