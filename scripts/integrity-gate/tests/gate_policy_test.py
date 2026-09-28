"""Exercise exact-SHA attestation refusal with a typed local evidence server fixture."""

from __future__ import annotations

import copy
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrity_http import IntegrityError, JsonObject
from integrity_policy import gate_pr

SHA = "0123456789012345678901234567890123456789"


class EvidenceFixture:
    """Respond to fixed local endpoints and capture statuses without external effects."""

    def __init__(self) -> None:
        """Build a valid exact-head review and structured eval comment."""
        self.document: JsonObject = {
            "schema_version": 1,
            "task_ref": "7",
            "frozen_sha": "base",
            "head_sha": SHA,
            "evals": [],
        }
        self.review = f"<!-- coderails-review-summary v1 pr=7 head_sha={SHA} -->"
        self.marker = f"<!-- coderails-eval-summary v1 pr=7 head_sha={SHA} result=GO verification_level=1 -->"
        self.files: list[JsonObject] = [{"filename": "scripts/example.py"}]
        self.diff = "diff --git a/scripts/example.py b/scripts/example.py\n+x\n"
        self.statuses: list[JsonObject] = []
        self.posts: list[tuple[str, str, str]] = []
        self.failure = ""
        self.calls: list[str] = []
        self.head = SHA

    def check(self, target: str) -> None:
        """Record every read and raise a configured transport refusal."""
        self.calls.append(target)
        if target == self.failure:
            raise IntegrityError("fixture fetch denied")

    def get_object(self, target: str) -> JsonObject:
        """Return only the fixture's authoritative PR head."""
        self.check(target)
        return {"head": {"sha": self.head}}

    def get_array(self, target: str) -> list[JsonObject]:
        """Return independent changed-file or commit-status arrays."""
        self.check(target)
        return copy.deepcopy(self.statuses if target.startswith("commits/") else self.files)

    def get(self, target: str, accept: str = "application/vnd.github+json") -> str:
        """Return the reviewed diff only for the real diff media type."""
        self.check("diff")
        if target != "pulls/7" or accept != "application/vnd.github.v3.diff":
            raise AssertionError((target, accept))
        return self.diff

    def comments(self, number: int) -> list[str]:
        """Return the exact review and eval artifacts in server order."""
        self.check("comments")
        if number != 7:
            raise AssertionError(number)
        return [self.review, self.marker + "\n```json\n" + json.dumps(self.document) + "\n```"]

    def post_status(self, sha: str, state: str, description: str) -> None:
        """Capture each attempted attestation for independent assertions."""
        self.posts.append((sha, state, description))


class GatePolicyTests(unittest.TestCase):
    """Mechanical refusals must never emit an independent success attestation."""

    def gate(self, client: EvidenceFixture, maximum: int = 204800) -> int:
        """Run the production policy and keep routine daemon diagnostics quiet."""
        with redirect_stdout(io.StringIO()):
            return gate_pr(client, 7, maximum, 720)

    def test_valid_exact_head_posts_pending_then_machine_attestation(self) -> None:
        """Fresh heads require an actual positive result with SHA-bound descriptions."""
        client = EvidenceFixture()
        self.assertEqual(self.gate(client), 0)
        self.assertEqual([post[1] for post in client.posts], ["pending", "success"])
        for sha, _, description in client.posts:
            self.assertEqual(sha, SHA)
            self.assertIn("sha=" + SHA, description)
        for token in ("integrity=pass", "evidence=review,eval,commands", "independent=machine", "provenance=sha-bound"):
            self.assertIn(token, client.posts[-1][2])

    def test_missing_review_and_protected_policy_paths(self) -> None:
        """Missing review is a retryable error; protected changes produce terminal failure."""
        client = EvidenceFixture()
        client.review = ""
        self.assertEqual(self.gate(client), 1)
        self.assertEqual(client.posts[-1][1], "error")
        self.assertIn("review_evidence_missing", client.posts[-1][2])
        for filename in (
            "scripts/integrity-gate/evil.py",
            "skills/dashboard/page.ts",
            "launchd/job.plist",
            ".github/workflows/action.yml",
        ):
            client = EvidenceFixture()
            client.files = [{"filename": filename}]
            self.assertEqual(self.gate(client), 0)
            self.assertEqual(client.posts[-1][1], "failure")
            self.assertIn("integrity=fail", client.posts[-1][2])
            self.assertNotIn("diff", client.calls)

    def test_fetch_shape_and_oversize_refusals_never_post_success(self) -> None:
        """Every remote evidence boundary and bounded diff fails closed independently."""
        for endpoint in (
            "pulls/7",
            "comments",
            f"commits/{SHA}/statuses?per_page=100",
            "pulls/7/files?per_page=100",
            "diff",
        ):
            client = EvidenceFixture()
            client.failure = endpoint
            self.assertEqual(self.gate(client), 1)
            self.assertTrue(all(post[1] != "success" for post in client.posts))
        for files in ([], [{"filename": ""}], [{"filename": None}]):
            client = EvidenceFixture()
            client.files = files
            self.assertEqual(self.gate(client), 1)
            self.assertIn("file_list_invalid", client.posts[-1][2])
        for diff in ("", "é" * 5):
            client = EvidenceFixture()
            client.diff = diff
            self.assertEqual(self.gate(client, 9), 0)
            self.assertIn("diff_invalid_or_oversize", client.posts[-1][2])

    def test_document_and_literal_marker_bindings(self) -> None:
        """Foreign heads and malformed structured evidence cannot become an attestation."""
        changes: tuple[tuple[str, Any], ...] = (
            ("schema_version", True),
            ("schema_version", 0),
            ("task_ref", None),
            ("head_sha", "b" * 40),
            ("evals", {}),
        )
        for key, value in changes:
            client = EvidenceFixture()
            client.document[key] = value
            self.assertEqual(self.gate(client), 1)
            self.assertIn("eval_evidence_invalid", client.posts[-1][2])
        client = EvidenceFixture()
        client.marker = client.marker.replace("result=GO", "result=NO-GO")
        self.assertEqual(self.gate(client), 0)
        self.assertIn("eval_result_not_go", client.posts[-1][2])
        client = EvidenceFixture()
        client.head = ""
        self.assertEqual(self.gate(client), 1)
        self.assertEqual(client.posts, [])


if __name__ == "__main__":
    unittest.main()
