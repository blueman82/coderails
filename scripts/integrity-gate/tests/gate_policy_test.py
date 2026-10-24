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

from scripts.lib.eval_integrity import suite_hash

SHA = "0123456789012345678901234567890123456789"


class EvidenceFixture:
    """Respond to fixed local endpoints and capture statuses without external effects."""

    def __init__(self) -> None:
        """Build a valid exact-head review and structured eval comment."""
        self.document: JsonObject = {
            "schema_version": 1,
            "scope": "pr",
            "task_ref": "7",
            "verification_level": 1,
            "verification_justification": "Run a direct artifact check.",
            "frozen_at": "2026-10-24T11:42:17Z",
            "frozen_sha": "a" * 40,
            "head_sha": SHA,
            "evals": [
                {
                    "id": "E1",
                    "priority": "P0",
                    "mode": "agent-run",
                    "status": "pass",
                    "assert": "The artifact behaves as required.",
                    "expected": "A passing result.",
                    "verifier_instruction": "Drive the final artifact.",
                    "evidence": "Observed passing run.",
                }
            ],
        }
        self.document["frozen_hash"] = suite_hash(self.document)
        self.review = f"<!-- coderails-review-summary v1 pr=7 head_sha={SHA} -->\n\n## No findings"
        self.marker = f"<!-- coderails-eval-summary v1 pr=7 head_sha={SHA} result=GO verification_level=1 -->"
        self.files: list[JsonObject] = [{"filename": "scripts/example.py"}]
        self.diff = "diff --git a/scripts/example.py b/scripts/example.py\n+x\n"
        self.statuses: list[JsonObject] = []
        self.posts: list[tuple[str, str, str]] = []
        self.failure = ""
        self.calls: list[str] = []
        self.head = SHA
        self.state = "open"
        self.base = "main"
        self.open_main: list[JsonObject] = [{"number": 7, "head": {"sha": SHA}, "base": {"ref": "main"}}]
        self.changed_files: int | None = None
        self.comments_available = True
        self.review_author = "owner"
        self.eval_author = "owner"
        self.eval_json_override: str | None = None
        self.late_eval = ""
        self.remove_comments_during_diff = False

    def check(self, target: str) -> None:
        """Record every read and raise a configured transport refusal."""
        self.calls.append(target)
        if target == self.failure:
            raise IntegrityError("fixture fetch denied")

    def get_object(self, target: str) -> JsonObject:
        """Return only the fixture's authoritative PR head."""
        self.check(target)
        return {
            "head": {"sha": self.head},
            "base": {"ref": self.base},
            "state": self.state,
            "changed_files": self.changed_files or len(self.files),
        }

    def get_array(self, target: str) -> list[JsonObject]:
        """Return independent changed-file or commit-status arrays."""
        self.check(target)
        if target.startswith("commits/"):
            page = int(target.rsplit("page=", 1)[1])
            return copy.deepcopy(self.statuses[(page - 1) * 100 : page * 100])
        if target.startswith("pulls?state=open&base=main&"):
            page = int(target.rsplit("page=", 1)[1])
            return copy.deepcopy(self.open_main[(page - 1) * 100 : page * 100])
        page = int(target.rsplit("page=", 1)[1]) if "page=" in target else 1
        return copy.deepcopy(self.files[(page - 1) * 100 : page * 100])

    def get(self, target: str, accept: str = "application/vnd.github+json") -> str:
        """Return the reviewed diff only for the real diff media type."""
        self.check("diff")
        if getattr(self, "remove_comments_during_diff", False):
            self.comments_available = False
        if target != "pulls/7" or accept != "application/vnd.github.v3.diff":
            raise AssertionError((target, accept))
        return self.diff

    def owner_login(self) -> str:
        """Return the fixture repository owner."""
        return "owner"

    def comments(self, number: int) -> list[JsonObject]:
        """Return the exact review and eval artifacts in server order."""
        self.check("comments")
        if number != 7:
            raise AssertionError(number)
        comments = (
            [
                {"body": self.review, "user": {"login": self.review_author}},
                {
                    "body": f"{self.marker}\n```json\n{self.eval_json_override or json.dumps(self.document)}\n```",
                    "user": {"login": self.eval_author},
                },
            ]
            if self.comments_available
            else []
        )
        if self.late_eval:
            comments.append({"body": self.late_eval, "user": {"login": "owner"}})
        return comments

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
        self.assertEqual([post[1] for post in client.posts], ["success"])
        for sha, _, description in client.posts:
            self.assertEqual(sha, SHA)
            self.assertIn("sha=" + SHA, description)
        for token in ("integrity=pass", "evidence=review,eval,commands", "source=actions", "provenance=sha-bound"):
            self.assertIn(token, client.posts[-1][2])
        self.assertLessEqual(len(client.posts[-1][2]), 140)

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
            "scripts.py",
            "scripts/__init__.py",
            "scripts/lib.py",
            "scripts/lib/__init__.py",
            "scripts/lib/artifact_io.py",
            "scripts/lib/eval_integrity.py",
            "scripts/lib/eval_signing.py",
            "scripts/lib/eval_trace.py",
            "scripts/lib/config.py",
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
            "pulls/7/files?per_page=100&page=1",
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
            self.assertIn("file_count_invalid" if not files else "file_list_invalid", client.posts[-1][2])
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

    def test_terminal_success_is_rechecked_after_comment_change(self) -> None:
        """A previous success cannot hide a removed review."""
        client = EvidenceFixture()
        client.statuses = [{"context": "integrity-review", "state": "success"}]
        client.review = ""
        self.assertEqual(self.gate(client), 1)
        self.assertEqual(client.posts[-1][1], "error")
        self.assertIn("review_evidence_missing", client.posts[-1][2])

    def test_empty_command_and_provenance_do_not_attest(self) -> None:
        """A marker cannot replace missing command evidence."""
        client = EvidenceFixture()
        client.document["verification_level"] = 1
        client.document["verification_justification"] = "Run the CLI against the final artifact."
        client.document["frozen_at"] = "2026-10-24T11:42:17Z"
        client.document["frozen_sha"] = "a" * 40
        client.document["evals"] = [
            {"id": "E1", "priority": "P0", "mode": "scripted", "status": "pass", "evidence": "ok"}
        ]
        self.assertEqual(self.gate(client), 1)
        self.assertIn("eval_evidence_invalid", client.posts[-1][2])

    def test_protected_path_after_first_file_page_is_checked(self) -> None:
        """The file after the first page still blocks success."""
        client = EvidenceFixture()
        client.files = [{"filename": f"docs/safe-{index}.md"} for index in range(100)]
        client.files.append({"filename": ".github/workflows/integrity-review.yml"})
        self.assertEqual(self.gate(client), 0)
        self.assertEqual(client.posts[-1][1], "failure")
        self.assertIn("policy_path_", client.posts[-1][2])
        self.assertIn("pulls/7/files?per_page=100&page=2", client.calls)

    def test_renamed_protected_path_is_checked(self) -> None:
        """A rename cannot hide the protected source path."""
        client = EvidenceFixture()
        client.files = [{"filename": "docs/old-gate.py", "previous_filename": "scripts/merge.py", "status": "renamed"}]
        self.assertEqual(self.gate(client), 0)
        self.assertEqual(client.posts[-1][1], "failure")

    def test_tampered_frozen_oracle_cannot_attest(self) -> None:
        """A changed oracle must fail its frozen hash check."""
        client = EvidenceFixture()
        client.document["evals"][0]["assert"] = "Changed after the freeze."
        self.assertEqual(self.gate(client), 1)
        self.assertIn("eval_evidence_invalid", client.posts[-1][2])

    def test_unhashable_eval_id_posts_failure(self) -> None:
        """Malformed owner JSON must produce a newer error status on the same head."""
        malformed_ids: tuple[object, ...] = ([], {})
        for malformed in malformed_ids:
            client = EvidenceFixture()
            client.document["evals"][0]["id"] = malformed
            self.assertEqual(self.gate(client), 1)
            self.assertEqual(client.posts[-1][1], "error")
            self.assertIn("eval_evidence_invalid", client.posts[-1][2])

    def test_negative_grading_chain_length_replaces_old_success(self) -> None:
        """Bad owner grading data must post a newer error on the same head."""
        for length in (-1, -2):
            with self.subTest(chain_len=length):
                client = EvidenceFixture()
                client.statuses = [{"context": "integrity-review", "state": "success"}]
                client.document["grading"] = {"chain_len": length}
                self.assertEqual((self.gate(client), client.posts[-1][:2]), (1, (SHA, "error")))
                self.assertIn("eval_evidence_invalid", client.posts[-1][2])

    def test_deep_owner_eval_replaces_old_success_with_error(self) -> None:
        """Deep JSON cannot leave a prior pass as the latest exact-head status."""
        for deep in ("[" * 1100 + "0" + "]" * 1100, '{"x":' * 1100 + "0" + "}" * 1100):
            with self.subTest(shape="array" if deep.startswith("[") else "object"):
                client = EvidenceFixture()
                client.statuses = [{"context": "integrity-review", "state": "success"}]
                valid = json.dumps(client.document)
                client.eval_json_override = valid[:-1] + ',"nested":' + deep + "}"
                self.assertEqual(self.gate(client), 1)
                self.assertEqual(client.posts[-1][0], SHA)
                self.assertEqual(client.posts[-1][1], "error")
                self.assertIn("eval_evidence_invalid", client.posts[-1][2])

    def test_unexpected_evaluation_fault_attempts_sanitized_error_status(self) -> None:
        """A future parser bug is visible and attempts a current-head refusal."""
        client = EvidenceFixture()

        def broken_comments(number: int) -> list[JsonObject]:
            raise RuntimeError("untrusted comment content")

        client.comments = broken_comments  # type: ignore[method-assign]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(gate_pr(client, 7, 204800, 720), 1)
        self.assertEqual(client.posts[-1][:2], (SHA, "error"))
        self.assertIn("evaluation_internal_error", client.posts[-1][2])
        self.assertIn("RuntimeError", output.getvalue())
        self.assertNotIn("untrusted comment content", output.getvalue())

    def test_known_head_comment_and_owner_errors_replace_old_success(self) -> None:
        """Bad comment fields or owner lookup still attempt a newer error status."""
        for failure in ("missing_user", "owner_fetch"):
            with self.subTest(failure=failure):
                client = EvidenceFixture()
                client.statuses = [{"context": "integrity-review", "state": "success"}]
                if failure == "missing_user":
                    client.comments = lambda number: [{"body": "owner text", "user": None}]  # type: ignore[method-assign]
                else:

                    def owner_fetch_error() -> str:
                        raise IntegrityError("owner fetch refused")

                    client.owner_login = owner_fetch_error  # type: ignore[method-assign]
                self.assertEqual((self.gate(client), client.posts[-1][:2]), (1, (SHA, "error")))

    def test_removed_eval_comment_overrides_previous_success(self) -> None:
        """Deleting the eval makes the next status a failure."""
        client = EvidenceFixture()
        client.statuses = [{"context": "integrity-review", "state": "success"}]
        client.comments = lambda number: [{"body": client.review, "user": {"login": "owner"}}]  # type: ignore[method-assign]
        self.assertEqual(self.gate(client), 1)
        self.assertEqual(client.posts[-1][1], "error")
        self.assertIn("eval_evidence_missing", client.posts[-1][2])

    def test_comment_deleted_during_check_never_posts_older_success(self) -> None:
        """The status cannot pass from comments removed before the final post."""
        client = EvidenceFixture()
        client.remove_comments_during_diff = True
        self.assertNotEqual(self.gate(client), 0)
        self.assertNotIn("success", [post[1] for post in client.posts])

    def test_newer_owner_eval_during_check_overrides_older_go(self) -> None:
        """A later owner NO-GO cannot leave the old GO as the current status."""
        client = EvidenceFixture()
        original = client.get

        def change_during_diff(target: str, accept: str = "application/vnd.github+json") -> str:
            result = original(target, accept)
            client.late_eval = client.marker.replace("result=GO", "result=NO-GO")
            return result

        client.get = change_during_diff  # type: ignore[method-assign]
        self.assertNotEqual(self.gate(client), 0)
        self.assertNotIn("success", [post[1] for post in client.posts])

    def test_api_file_cap_cannot_hide_a_protected_file(self) -> None:
        """A PR with 3001 files cannot attest from the API's first 3000."""
        client = EvidenceFixture()
        client.changed_files = 3001
        client.files = [{"filename": f"docs/safe-{index}.md"} for index in range(3000)]
        self.assertNotEqual(self.gate(client), 0)
        self.assertNotIn("success", [post[1] for post in client.posts])

    def test_foreign_comment_cannot_forge_either_artifact(self) -> None:
        """Only GitHub comments by the live owner can provide either artifact."""
        for artifact in ("review", "eval"):
            client = EvidenceFixture()
            if artifact == "review":
                client.review_author = "other"
            else:
                client.eval_author = "other"
            self.assertNotEqual(self.gate(client), 0)
            self.assertNotIn("success", [post[1] for post in client.posts])
        client = EvidenceFixture()
        self.assertEqual(self.gate(client), 0)
        self.assertEqual(client.posts[-1][1], "success")


if __name__ == "__main__":
    unittest.main()
