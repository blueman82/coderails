"""Verify queue schema, owner-only files, silent rejection and canonical hashes."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from audit_test_support import FIXTURES, invoke


class QueueTests(unittest.TestCase):
    """Use isolated HOME directories and independent byte/hash oracles."""

    def test_proposal_schema_hash_modes_default_and_idempotency(self) -> None:
        """Only six whitelisted input fields determine a deterministic pending filename."""
        proposal = (FIXTURES / "queue-proposal.json").read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = root / "queue"
            arguments = ("--queue-dir", str(queue), "--count", "3", "--sessions", '["s1","s2","s3"]')
            result = invoke("write_queue_entry", root, *arguments, stdin=proposal)
            self.assertEqual(result.returncode, 0, result.stderr)
            digest = result.stdout.strip()
            self.assertEqual(len(digest), 64)
            path = queue / f"{digest}.json"
            entry = json.loads(path.read_text())
            self.assertEqual(set(entry), {"hash", "toolName", "toolInput", "createdAt", "status"})
            self.assertEqual(entry["hash"], digest)
            self.assertEqual(entry["status"], "pending")
            self.assertEqual(entry["toolName"], "workflow-audit:propose-skill")
            self.assertIsInstance(entry["createdAt"], int)
            self.assertEqual(
                set(entry["toolInput"]),
                {"cluster_ngram", "count", "sessions", "task_summary", "proposed_name", "proposed_description"},
            )
            canonical = json.dumps(entry["toolInput"], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), digest)
            self.assertEqual(queue.stat().st_mode & 0o777, 0o700)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(invoke("write_queue_entry", root, *arguments, stdin=proposal).stdout, result.stdout)
            self.assertEqual(len(list(queue.iterdir())), 1)
            default = invoke(
                "write_queue_entry", root, "--count", "3", "--sessions", '["s1","s2","s3"]', stdin=proposal
            )
            self.assertEqual(default.stdout, result.stdout)
            self.assertTrue((root / ".claude/coderails-dashboard/approvals" / path.name).is_file())

    def test_observed_legacy_decimal_unicode_hash(self) -> None:
        """Pin the actual legacy jq writer result without retaining a runtime jq dependency."""
        source = (
            '{"verdict":"propose","task_summary":"café\\u007f",'
            '"cluster_ngram":[1.0,-0.0,1e-6,1e20,1e-7,123456789012345678901234567890],'
            '"proposed_name":"n","proposed_description":"d"}'
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = invoke("write_queue_entry", root, "--count", "3", "--sessions", '["s"]', stdin=source)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "ca92f1d2fc510c44d08ef0e726f4d83bb32cd09676f8ef9e5112844c2436c88e")

    def test_no_write_for_reject_absent_or_malformed(self) -> None:
        """Refuse malformed input distinctly while non-proposals remain silent no-ops."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for source in ('{"verdict":"reject"}', "{}"):
                result = invoke("write_queue_entry", root, stdin=source)
                self.assertEqual((result.returncode, result.stdout), (0, ""))
                self.assertEqual(list(root.iterdir()), [])
            for source in ("{broken", '"string"', "null", "[]"):
                result = invoke("write_queue_entry", root, stdin=source)
                self.assertEqual(result.returncode, 1)
                self.assertIn("jq_parse_error:stdin", result.stderr)
                self.assertEqual(list(root.iterdir()), [])
            help_result = invoke("write_queue_entry", root, "--help")
            self.assertEqual(help_result.returncode, 0)
            self.assertIn("queue-dir", help_result.stdout)

    def test_whitelist_and_numeric_fallback(self) -> None:
        """Drop raw transcript extras but preserve judge-vetted text verbatim."""
        source = json.dumps(
            {
                "verdict": "propose",
                "task_summary": "SENTINEL_sk_live_99xyz",
                "raw_transcript_line": "must never survive",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = invoke("write_queue_entry", root, "--count", "bad", "--sessions", "{}", stdin=source)
            path = root / ".claude/coderails-dashboard/approvals" / f"{result.stdout.strip()}.json"
            self.assertTrue(path.is_file(), result.stderr)
            self.assertNotIn("must never survive", path.read_text())
            entry = json.loads(path.read_text())["toolInput"]
            self.assertEqual(entry["task_summary"], "SENTINEL_sk_live_99xyz")
            self.assertEqual((entry["count"], entry["sessions"], entry["cluster_ngram"]), (0, [], []))


if __name__ == "__main__":
    unittest.main()
