"""Exercise trusted comment provenance and literal SHA-bound gate decisions."""

from __future__ import annotations

import base64
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib import eval_artifact, git_common, review_artifact
from scripts.lib.integrity_status import verify_integrity_status


class TrustedGitTests(unittest.TestCase):
    """Pin trust fetch failures, newest verdicts, and integrity status validation."""

    def test_newest_eval_wins(self) -> None:
        """A later trusted refusal must supersede an earlier success."""
        good = eval_artifact.marker("1", "sha", "GO", "1") + '\n```json\n{"evals":[]}\n```'
        bad = eval_artifact.marker("1", "sha", "NO-GO", "2") + '\n```json\n{"latest":true}\n```'
        with patch.object(git_common, "trusted_comment_bodies", return_value=[good, bad]):
            summary = git_common.gate_eval_summary_for_pr("1", "sha")
        self.assertEqual(summary.status, 1)
        self.assertEqual(summary.verification_level, "2")
        self.assertEqual(summary.embed, '{"latest":true}')

    def test_fetch_failure_is_distinct_from_absence(self) -> None:
        """Fail closed on identity, permission and comment transport failures."""
        for stage in ("identity", "permission", "comments"):
            with patch.object(git_common, "trusted_comment_bodies", side_effect=git_common.TrustFetchError(stage)):
                self.assertEqual(git_common.gate_eval_summary_for_pr("1", "sha").status, 2)
                self.assertEqual(git_common.has_coderails_review_for_head("1", "sha"), 2)
        with patch.object(git_common, "trusted_comment_bodies", return_value=[]):
            self.assertEqual(git_common.gate_eval_summary_for_pr("1", "sha").status, 1)

    def test_literal_review_and_untrusted_identity(self) -> None:
        """Reject regex-like SHA substitutions and query-injection identities."""
        with patch.object(git_common, "trusted_comment_bodies", return_value=[review_artifact.marker("1", "axb")]):
            self.assertEqual(git_common.has_coderails_review_for_head("1", "a.b"), 1)
        with patch.dict(os.environ, {"_PR_TRUSTED_LOGIN": 'x" or true'}), self.assertRaises(git_common.TrustFetchError):
            git_common.trusted_comment_bodies("1")

    def test_permission_and_paginated_filter(self) -> None:
        """READ access never qualifies; WRITE uses an exact authenticated filter."""
        with patch.dict(os.environ, {"_PR_TRUSTED_LOGIN": "writer", "_PR_TRUSTED_PERMISSION": "READ"}):
            self.assertEqual(git_common.trusted_comment_bodies("1"), [])
        encoded = base64.b64encode(b"trusted body").decode()
        response = subprocess.CompletedProcess(["gh"], 0, encoded + "\ninvalid!\n", "")
        with (
            patch.dict(os.environ, {"_PR_TRUSTED_LOGIN": "writer", "_PR_TRUSTED_PERMISSION": "WRITE"}),
            patch.object(git_common, "repo", return_value="o/r"),
            patch.object(git_common, "run", return_value=response) as run,
        ):
            self.assertEqual(git_common.trusted_comment_bodies("1"), ["trusted body"])
            self.assertIn("--paginate", run.call_args.args)
            self.assertIn('select(.user.login == "writer")', run.call_args.args[-1])

    def test_integrity_creator_sha_and_newest_status(self) -> None:
        """A success label alone cannot satisfy root-owned SHA attestation."""
        good = '{"state":"success","creator":{"login":"machine"},"description":"integrity=pass sha=abc"}'
        for record in (
            good.replace("machine", "attacker"),
            good.replace("abc", "old"),
            good.replace("success", "pending"),
        ):
            response = subprocess.CompletedProcess(["gh"], 0, f"[{record},{good}]", "")
            with (
                patch.object(git_common, "repo", return_value="o/r"),
                patch.object(git_common, "run", return_value=response),
                self.assertRaises(git_common.WorkflowError),
            ):
                verify_integrity_status("abc", "machine")
        response = subprocess.CompletedProcess(["gh"], 0, f"[{good}]\n[]", "")
        with (
            patch.object(git_common, "repo", return_value="o/r"),
            patch.object(git_common, "run", return_value=response),
        ):
            verify_integrity_status("abc", "machine")


if __name__ == "__main__":
    unittest.main()
