"""Refuse SHA-wide success when PR base branches or open main PRs conflict."""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_policy_test import SHA, EvidenceFixture  # type: ignore[import-not-found]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrity_http import JsonObject, object_value
from integrity_policy import gate_pr


class SharedShaTests(unittest.TestCase):
    """One PR's evidence cannot attest a different PR at the same commit."""

    def gate(self, client: EvidenceFixture) -> int:
        """Run the policy without routine diagnostic output."""
        with redirect_stdout(io.StringIO()):
            return gate_pr(client, 7, 204800, 720)

    def test_non_main_pr_cannot_replace_a_main_pr_failure_on_shared_sha(self) -> None:
        """An intermediate-base PR cannot overwrite the latest failure on a shared commit."""
        client = EvidenceFixture()
        client.base = "feature/base"
        client.posts.append((SHA, "failure", f"integrity=fail sha={SHA} reason=policy_path"))
        self.gate(client)
        self.assertEqual(client.posts[-1][1], "failure")
        self.assertEqual(len(client.posts), 1)

    def test_two_main_prs_with_one_sha_never_post_success(self) -> None:
        """A passing PR cannot hide a second main PR's missing evidence."""
        client = EvidenceFixture()
        client.open_main.append({"number": 8, "head": {"sha": SHA}, "base": {"ref": "main"}})
        self.assertNotEqual(self.gate(client), 0)
        self.assertEqual(client.posts[-1][1], "error")
        self.assertNotIn("success", [post[1] for post in client.posts])

    def test_shared_sha_on_second_open_pr_page_is_refused(self) -> None:
        """The first page alone cannot authorize a shared commit."""
        client = EvidenceFixture()
        client.open_main.extend(
            {"number": number, "head": {"sha": f"{number:040x}"}, "base": {"ref": "main"}} for number in range(100, 200)
        )
        client.open_main.append({"number": 8, "head": {"sha": SHA}, "base": {"ref": "main"}})
        self.assertNotEqual(self.gate(client), 0)
        self.assertEqual(client.posts[-1][1], "error")
        self.assertIn("pulls?state=open&base=main&per_page=100&page=2", client.calls)

    def test_failed_main_roster_fetch_cannot_post_success(self) -> None:
        """A failed duplicate check makes a previous success stale."""
        client = EvidenceFixture()
        client.posts.append((SHA, "success", f"integrity=pass sha={SHA}"))
        client.failure = "pulls?state=open&base=main&per_page=100&page=1"
        self.assertNotEqual(self.gate(client), 0)
        self.assertEqual(client.posts[-1][1], "error")

    def test_malformed_base_with_known_head_replaces_previous_success(self) -> None:
        """Malformed PR base data must not leave an older success as latest."""
        client = EvidenceFixture()
        client.posts.append((SHA, "success", f"integrity=pass sha={SHA}"))
        original = client.get_object

        def malformed_base(target: str) -> JsonObject:
            pr = object_value(original(target))
            pr["base"] = None
            return pr

        client.get_object = malformed_base
        self.assertNotEqual(self.gate(client), 0)
        self.assertEqual(client.posts[-1][1], "error")

    def test_base_retargeted_after_roster_check_replaces_success(self) -> None:
        """The final PR read must refuse a head retargeted away from main."""
        client = EvidenceFixture()
        original = client.get_object
        reads = 0

        def retargeted(target: str) -> JsonObject:
            nonlocal reads
            reads += 1
            pr = object_value(original(target))
            if reads > 1:
                pr["base"] = {"ref": "feature/base"}
            return pr

        client.get_object = retargeted
        self.assertNotEqual(self.gate(client), 0)
        self.assertEqual(client.posts[-1][1], "error")

    def test_latest_head_must_match_attested_head_before_posting(self) -> None:
        """A moved head gets no stale success status."""
        client = EvidenceFixture()
        original = client.get_object
        reads = 0

        def moving_head(target: str) -> JsonObject:
            nonlocal reads
            reads += 1
            return {"head": {"sha": SHA if reads == 1 else "b" * 40}} if target == "pulls/7" else original(target)

        client.get_object = moving_head
        self.assertNotEqual(self.gate(client), 0)
        self.assertNotIn("success", [post[1] for post in client.posts])


if __name__ == "__main__":
    unittest.main()
