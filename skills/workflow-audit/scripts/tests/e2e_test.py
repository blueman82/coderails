"""Verify the scanner-to-cluster pipeline preserves privacy without creating skills."""

import json
import tempfile
import unittest
from pathlib import Path

from audit_test_support import SCRIPTS, invoke, place, transcript


class PipelineTests(unittest.TestCase):
    """Use complete synthetic CLI flows with no transcript or skill mutations."""

    def test_repeated_pipeline_and_no_creation(self) -> None:
        """Surface the known trigram across three projects and leave all skills alone."""
        events = [
            {"name": "Bash", "input": {"command": "git log --oneline"}},
            {"name": "Bash", "input": {"command": "git push origin"}},
            {"name": "Skill", "input": {"skill": "prime"}},
        ]
        skills = SCRIPTS.parents[1]
        before = sorted(path.name for path in skills.iterdir() if path.is_dir())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(3):
                place(root, f"project{index}", f"session{index}", transcript(events))
            scan = invoke("scan_transcripts", root, "--all-projects", "--days", "36500")
            result = invoke("cluster_ngrams", root, stdin=scan.stdout)
            self.assertEqual((scan.returncode, result.returncode), (0, 0))
            cluster = json.loads(result.stdout)["clusters"][0]
            self.assertEqual(
                cluster,
                {
                    "ngram": ["Bash:git log", "Bash:git push", "Skill:prime"],
                    "n": 3,
                    "count": 3,
                    "sessions": ["session0", "session1", "session2"],
                },
            )
            self.assertEqual(list(root.rglob("SKILL.md")), [])
        self.assertEqual(sorted(path.name for path in skills.iterdir() if path.is_dir()), before)

    def test_secret_never_reaches_clusters_and_unicode_survives(self) -> None:
        """A real planted secret disappears while its permitted command head clusters."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = transcript(
                [
                    {"name": "Bash", "input": {"command": "curl -H Authorization:SENTINEL_sk_live_99xyz"}},
                    {"name": "Read"},
                ]
            )
            self.assertIn("SENTINEL_sk_live_99xyz", source)
            for index in range(3):
                place(root, "project", str(index), source)
            scan = invoke("scan_transcripts", root, "--days", "36500")
            result = invoke("cluster_ngrams", root, stdin=scan.stdout)
            self.assertNotIn("SENTINEL_sk_live_99xyz", scan.stdout + result.stdout)
            self.assertIn("Bash:curl -H", result.stdout)
            for index in range(3):
                place(
                    root,
                    "project",
                    str(index),
                    transcript([{"name": "Bash", "input": {"command": "echo café-日本語 --flag"}}]),
                )
            scan = invoke("scan_transcripts", root, "--days", "36500")
            self.assertIn("echo café-日本語", scan.stdout)
            result = invoke("cluster_ngrams", root, stdin=scan.stdout)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["clusters"], [])

    def test_no_candidates_and_empty_input_are_clean(self) -> None:
        """Distinct single-event sessions and an empty corpus legitimately have no clusters."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, tool in enumerate(("Read", "Write", "Grep")):
                place(root, "project", str(index), transcript([{"name": tool}]))
            scan = invoke("scan_transcripts", root, "--days", "36500")
            result = invoke("cluster_ngrams", root, stdin=scan.stdout)
            self.assertEqual((scan.returncode, result.returncode), (0, 0))
            self.assertEqual(json.loads(result.stdout)["clusters"], [])
            self.assertNotIn("jq_parse_error", scan.stderr + result.stderr)
            empty = json.loads(invoke("cluster_ngrams", root).stdout)
            self.assertEqual(
                empty,
                {"scanned_sessions": 0, "clusters": [], "diagnostics": {"below_threshold": 0, "truncated": False}},
            )


if __name__ == "__main__":
    unittest.main()
