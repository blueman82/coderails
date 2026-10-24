"""Bound commit-status writes while checking fresh evidence on every run."""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_policy_test import SHA, EvidenceFixture  # type: ignore[import-not-found]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrity_policy import gate_pr


class StatusReconciliationTests(unittest.TestCase):
    """A repeated run must not consume the finite GitHub status budget."""

    def gate(self, client: EvidenceFixture) -> int:
        """Run the full policy and silence routine diagnostics."""
        with redirect_stdout(io.StringIO()):
            return gate_pr(client, 7, 204800, 720)

    @staticmethod
    def prior_status(client: EvidenceFixture, login: str = "github-actions[bot]") -> tuple[str, str, str]:
        """Seed a server status from the fixture's last posted result."""
        prior: tuple[str, str, str] = client.posts[-1]
        client.statuses = [
            {"context": "integrity-review", "state": prior[1], "description": prior[2], "creator": {"login": login}}
        ]
        client.posts.clear()
        return prior

    def test_unchanged_success_rechecks_evidence_without_new_status(self) -> None:
        """The hourly check reads evidence without consuming another status."""
        client = EvidenceFixture()
        self.assertEqual(self.gate(client), 0)
        self.prior_status(client)
        self.assertEqual(self.gate(client), 0)
        self.assertEqual(client.posts, [])
        self.assertIn("comments", client.calls)
        self.assertIn("diff", client.calls)

    def test_changed_evidence_replaces_old_success(self) -> None:
        """Deleting review evidence overwrites a previous success."""
        client = EvidenceFixture()
        self.assertEqual(self.gate(client), 0)
        self.prior_status(client)
        client.review = ""
        self.assertEqual(self.gate(client), 1)
        self.assertEqual(client.posts[-1][1], "error")

    def test_foreign_latest_status_never_satisfies_idempotence(self) -> None:
        """A matching result from another actor still needs the trusted bot."""
        client = EvidenceFixture()
        self.assertEqual(self.gate(client), 0)
        prior = self.prior_status(client, "other")
        self.assertEqual(self.gate(client), 0)
        self.assertEqual(client.posts, [prior])

    def test_status_budget_retires_sha_before_cap(self) -> None:
        """A high count becomes a terminal error while one write remains."""
        client = EvidenceFixture()
        self.assertEqual(self.gate(client), 0)
        prior = self.prior_status(client)
        client.statuses *= 999
        self.assertEqual(self.gate(client), 1)
        self.assertEqual(len(client.posts), 1)
        self.assertEqual(client.posts[-1][1], "error")
        self.assertIn("status_budget_exhausted", client.posts[-1][2])
        self.assertEqual(prior[1], "success")

    def test_retired_sha_cannot_regain_success(self) -> None:
        """A fresh evaluation cannot reactivate a retired commit."""
        client = EvidenceFixture()
        client.statuses = [
            {
                "context": "integrity-review",
                "state": "error",
                "description": f"integrity=fail sha={SHA} reason=status_budget_exhausted",
                "creator": {"login": "github-actions[bot]"},
            }
            for _ in range(900)
        ]
        self.assertEqual(self.gate(client), 1)
        self.assertEqual(client.posts, [])

    def test_status_context_case_does_not_evade_budget(self) -> None:
        """GitHub counts status contexts without regard to case."""
        client = EvidenceFixture()
        client.statuses = [
            {"context": "INTEGRITY-REVIEW", "state": "success", "description": "old", "creator": {"login": "other"}}
            for _ in range(900)
        ]
        self.assertEqual(self.gate(client), 1)
        self.assertEqual(client.posts[-1][1], "error")
        self.assertIn("status_budget_exhausted", client.posts[-1][2])

    def test_status_history_fetch_failure_never_skips_success(self) -> None:
        """A failed status read cannot authorize a no-op success."""
        client = EvidenceFixture()
        client.failure = f"commits/{SHA}/statuses?per_page=100&page=1"
        self.assertEqual(self.gate(client), 1)
        self.assertNotIn("success", [post[1] for post in client.posts])

    def test_long_protected_path_has_fixed_bounded_reason(self) -> None:
        """A file name cannot exceed GitHub's description limit."""
        client = EvidenceFixture()
        client.files = [{"filename": "scripts/integrity-gate/" + "a" * 500}]
        self.assertEqual(self.gate(client), 0)
        self.assertEqual(client.posts[-1][1], "failure")
        self.assertEqual(client.posts[-1][2], f"integrity=fail sha={SHA} reason=policy_path_protected")
        self.assertLessEqual(len(client.posts[-1][2]), 140)


if __name__ == "__main__":
    unittest.main()
