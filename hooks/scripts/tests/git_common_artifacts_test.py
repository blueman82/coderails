"""Preserve authenticated review/eval reader parity with paginated gh fixtures."""

from __future__ import annotations

import base64
import os
import subprocess
import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib import eval_artifact, git_common, review_artifact

RUN = Callable[..., subprocess.CompletedProcess[str]]
SHA = "deadbeef"
REVIEW = review_artifact.marker("42", SHA)
GO = eval_artifact.marker("42", SHA, "GO", "1")
NO_GO = eval_artifact.marker("42", SHA, "NO-GO", "2")


def responder(rows: list[tuple[str, str]], permission: str = "WRITE", failure: str = "") -> RUN:
    """Provide exact authenticated gh responses, asserting the production query shape."""

    def invoke(*arguments: str, check: bool = False) -> subprocess.CompletedProcess[str]:
        """Handle only the expected live trust sequence and paginated comment command."""
        del check
        if arguments[:3] == ("gh", "api", "user"):
            stage, result = "identity", "trusted-bot"
        elif arguments[:3] == ("gh", "repo", "view"):
            stage, result = "permission", permission
        else:
            if arguments != (
                "gh",
                "api",
                "repos/o/r/issues/42/comments",
                "--paginate",
                "--jq",
                '.[] | select(.user.login == "trusted-bot") | (.body | @base64)',
            ):
                raise AssertionError(f"unexpected comment query: {arguments}")
            stage = "comments"
            result = "\n".join(
                base64.b64encode(body.encode()).decode() for author, body in rows if author == "trusted-bot"
            )
        return subprocess.CompletedProcess(arguments, int(stage == failure), result if stage != failure else "", "")

    return invoke


class GitArtifactTests(unittest.TestCase):
    """Reject spoofed, stale and untrusted artifacts without inheriting previous results."""

    def readers(
        self, rows: list[tuple[str, str]], permission: str = "WRITE", failure: str = ""
    ) -> tuple[tuple[int, str], git_common.EvalSummary]:
        """Exercise both public readers through their actual trust-fetch implementation."""
        with (
            patch.dict(os.environ, {"_PR_TRUSTED_LOGIN": "", "_PR_TRUSTED_PERMISSION": ""}),
            patch.object(git_common, "repo", return_value="o/r"),
            patch.object(git_common, "run", side_effect=responder(rows, permission, failure)),
        ):
            return git_common.gate_review_summary_for_pr("42", SHA), git_common.gate_eval_summary_for_pr("42", SHA)

    def test_permission_author_and_exact_identity_matrix(self) -> None:
        """Author equality plus WRITE/MAINTAIN/ADMIN is required independently of association."""
        for permission in ("WRITE", "MAINTAIN", "ADMIN"):
            review, result = self.readers([("trusted-bot", REVIEW), ("trusted-bot", GO)], permission)
            self.assertEqual(review, (0, ""))
            self.assertEqual((result.status, result.verification_level), (0, "1"))
        for permission in ("READ", "TRIAGE", "UNKNOWN"):
            review, result = self.readers([("trusted-bot", REVIEW), ("trusted-bot", GO)], permission)
            self.assertEqual(review, (1, ""))
            self.assertEqual(result, git_common.EvalSummary(1))
        for bodies in (
            [REVIEW, GO],
            [REVIEW.replace(SHA, "other"), GO.replace(SHA, "other")],
            [REVIEW.replace("v1", "v2"), GO.replace("v1", "v2")],
        ):
            author = "attacker" if bodies[0] == REVIEW else "trusted-bot"
            review, result = self.readers([(author, body) for body in bodies])
            self.assertEqual(review, (1, ""))
            self.assertEqual(result.status, 1)

    def test_fetch_failures_keep_distinct_reasons(self) -> None:
        """Expose which authenticated lookup failed, never quietly falling back to absence."""
        for stage in ("identity", "permission", "comments"):
            review, result = self.readers([], failure=stage)
            self.assertEqual(review, (2, stage))
            self.assertEqual(result, git_common.EvalSummary(2, failure_reason=stage))
        review, result = self.readers([])
        self.assertEqual(review, (1, ""))
        self.assertEqual(result, git_common.EvalSummary(1))
        with patch.dict(os.environ, {"_PR_TRUSTED_LOGIN": 'x" or true'}), patch.object(git_common, "run") as run:
            self.assertEqual(git_common.gate_review_summary_for_pr("42", SHA), (2, "identity"))
            run.assert_not_called()

    def test_pagination_and_multiline_markers(self) -> None:
        """Recognize an exact marker beyond a hundred rows and within surrounding prose."""
        filler = [("attacker", "filler")] * 105
        review, result = self.readers(filler)
        self.assertEqual(review[0], 1)
        self.assertEqual(result.status, 1)
        review, result = self.readers(filler + [("trusted-bot", "before\n" + REVIEW + "\nafter"), ("trusted-bot", GO)])
        self.assertEqual(review[0], 0)
        self.assertEqual(result.status, 0)

    def test_newest_trusted_verdict_and_exact_embed(self) -> None:
        """Select result and embed from the same latest trusted SHA-matching comment."""
        old = GO + '\n```json\n{"version":1}\n```'
        latest = NO_GO + '\n```json\n{"version":2}\n```'
        _, result = self.readers([("trusted-bot", old), ("trusted-bot", latest), ("attacker", old)])
        self.assertEqual((result.status, result.verification_level, result.embed), (1, "2", '{"version":2}'))
        _, result = self.readers([("trusted-bot", latest), ("trusted-bot", old)])
        self.assertEqual((result.status, result.verification_level, result.embed), (0, "1", '{"version":1}'))
        _, result = self.readers([])
        self.assertEqual(result, git_common.EvalSummary(1))
        _, result = self.readers([("attacker", old)])
        self.assertEqual(result, git_common.EvalSummary(1))


if __name__ == "__main__":
    unittest.main()
