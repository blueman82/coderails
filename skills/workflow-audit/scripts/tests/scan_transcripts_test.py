"""Preserve scanner privacy, mixed records, selection and diagnostic behavior."""

import tempfile
import unittest
from pathlib import Path

from audit_test_support import FIXTURES, invoke, place, rows, transcript


class ScanTests(unittest.TestCase):
    """Exercise actual scanner CLI exclusively over synthetic fixture corpora."""

    def test_fixture_shapes_privacy_and_corruption(self) -> None:
        """Keep whitelist event extraction and valid records beside corrupt lines."""
        expected = [
            {"tool": "Bash", "head": "git log"},
            {"tool": "Read"},
            {"tool": "Skill", "head": "prime"},
            {"tool": "Agent", "head": "general-purpose"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("small", "edge", "sentinel"):
                place(root, name, name, (FIXTURES / f"fixture-{name}.jsonl").read_text())
            result = invoke("scan_transcripts", root, "--project", "small", "--days", "36500")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                rows(result.stdout),
                [{"session_id": "small", "project_slug": "small", "event_count": 4, "events": expected}],
            )
            self.assertTrue(result.stderr.startswith("scanning file_count=1 total_mb="))
            self.assertNotIn("jq_parse_error", result.stderr)
            edge = invoke("scan_transcripts", root, "--project", "edge", "--days", "36500")
            self.assertEqual(
                rows(edge.stdout)[0]["events"],
                [{"tool": "Bash", "head": "npm test"}, {"tool": "mcp__claude-in-chrome__navigate"}],
            )
            sentinel = invoke("scan_transcripts", root, "--project", "sentinel", "--days", "36500")
            self.assertIn("SENTINEL_sk_live_99xyz", (FIXTURES / "fixture-sentinel.jsonl").read_text())
            self.assertNotIn("SENTINEL_sk_live_99xyz", sentinel.stdout)
            self.assertIn('"head":"curl -H"', sentinel.stdout)
            with (root / "small/small.jsonl").open("a") as stream:
                stream.write("{broken\n")
            corrupt = invoke("scan_transcripts", root, "--project", "small", "--days", "36500")
            self.assertIn("jq_parse_error:", corrupt.stderr)
            self.assertEqual(rows(corrupt.stdout)[0]["event_count"], 4)

    def test_selection_uses_message_time_and_own_session(self) -> None:
        """Narrow by project/time while ignoring mtime and excluding the active session."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            older = place(root, "ordered", "old", transcript([{"name": "Read"}], "2020-01-01T00:00:00Z"))
            place(root, "ordered", "new", transcript([{"name": "Write"}]))
            place(root, "other", "other", transcript([{"name": "Read"}]))
            older.touch()
            result = invoke("scan_transcripts", root, "--project", "ordered", "--last-sessions", "1")
            self.assertEqual([row["session_id"] for row in rows(result.stdout)], ["new"])
            result = invoke("scan_transcripts", root, "--project", "ordered", "--last-sessions", "50")
            self.assertEqual(len(rows(result.stdout)), 2)
            result = invoke("scan_transcripts", root, "--all-projects", "--days", "36500", own="new")
            self.assertEqual({row["session_id"] for row in rows(result.stdout)}, {"old", "other"})
            self.assertIn("skipped_own_session:", result.stderr)
            self.assertEqual(invoke("scan_transcripts", root, "--days", "14").stdout, "")
            (root / "empty").mkdir()
            self.assertEqual(invoke("scan_transcripts", root, "--project", "empty").stdout, "")

    def test_head_types_whitespace_unicode_and_help(self) -> None:
        """Never stringify structured argument fields or leak non-head command tokens."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events = [
                {"name": name, "input": {field: {"secret": "never leak"}}}
                for name, field in (("Skill", "skill"), ("Agent", "subagent_type"), ("Bash", "command"))
            ]
            events += [
                {"name": "Bash", "input": {"command": "   git    status --short"}},
                {"name": "Bash", "input": {"command": "echo café-日本語 --flag"}},
            ]
            place(root, "heads", "heads", transcript(events))
            result = invoke("scan_transcripts", root, "--days", "36500")
            self.assertEqual(result.returncode, 0)
            self.assertNotIn("never leak", result.stdout)
            self.assertEqual(
                [event["head"] for event in rows(result.stdout)[0]["events"]],
                ["", "", "", "git status", "echo café-日本語"],
            )
            help_result = invoke("scan_transcripts", root, "--help")
            self.assertEqual(help_result.returncode, 0)
            self.assertIn("WORKFLOW_AUDIT_ROOT", help_result.stdout)
            self.assertEqual(invoke("scan_transcripts", root, "--unknown").returncode, 1)


if __name__ == "__main__":
    unittest.main()
