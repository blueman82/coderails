"""Live authority still limits advisory receipt mode."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.receipt_hook_case import MERGE, MERGE_SHA, ReceiptHookCase


class AdvisoryGateTests(ReceiptHookCase):
    """Run the real precommand hook against an isolated session and repository."""

    def test_advisory_push_still_obeys_live_authority_denial(self) -> None:
        """A live push_main denial cannot be waived by advisory receipt mode."""
        self.configure("advisory")
        self.grant(denied=["push_main"])
        self.assertTrue(self.denied("action_authority_gate", self.payload("git push origin main")))
        self.assertEqual(self.reasons(), ["denied_authority_denied"])

    def test_advisory_plain_gh_merge_reserves_live_budget(self) -> None:
        """The precommand hook charges an uncertain raw gh merge against max_prs."""
        self.configure("advisory")
        self.grant(max_prs=1)
        self.assertFalse(self.denied("action_authority_gate", self.payload(MERGE)))
        self.assertEqual(len(list((self.loop / "s1" / "merges").glob("*.json"))), 1)
        self.assertTrue(self.denied("action_authority_gate", self.payload(MERGE)))
        self.assertIn("denied_max_prs_exceeded", self.reasons())

    def test_advisory_async_merge_with_live_budget_is_unbindable(self) -> None:
        """A live max_prs cannot count the downstack PRs an async request may merge."""
        self.configure("advisory")
        self.grant(max_prs=1)
        command = (
            "gh api --method PUT repos/acme/widgets/pulls/12/merge-async " f"-f sha={MERGE_SHA} -f merge_method=merge"
        )
        self.assertTrue(self.denied("action_authority_gate", self.payload(command)))
        self.assertEqual(list((self.loop / "s1" / "merges").glob("*.json")), [])
        self.assertIn("denied_binding_unknown", self.reasons())

    def test_unbindable_merge_with_live_cap_is_denied_before_remote_command(self) -> None:
        """An unknown PR or head cannot merge without using the live max_prs budget."""
        self.configure("advisory")
        self.grant(max_prs=1)
        remote = self.directory / "remote.log"
        gh = self.directory / "bin" / "gh"
        gh.write_text(
            f'#!/bin/sh\nif [ "$1 $2" = "pr view" ]; then '
            f'echo \'{{"baseRefName":"main","headRefOid":"{MERGE_SHA}"}}\'; '
            f'else echo "$*" >> "{remote}"; fi\n'
        )
        commands = (
            "gh pr merge 12 --squash",
            "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"x\"}) { id } }'",
        )
        for command in commands:
            with self.subTest(command=command):
                denied = self.denied("action_authority_gate", self.payload(command))
                if not denied:
                    subprocess.run(command, shell=True, env=self.environment, cwd=self.repo, check=True)
                self.assertTrue(denied)
                self.assertFalse(remote.exists())
                self.assertEqual(list((self.loop / "s1" / "merges").glob("*.json")), [])
        self.assertEqual(self.reasons(), ["denied_binding_unknown", "denied_binding_unknown"])

    def test_unbindable_merge_without_live_cap_remains_advisory(self) -> None:
        """Explicit advisory mode warns and allows when no session authority is active."""
        self.configure("advisory")
        self.assertFalse(self.denied("action_authority_gate", self.payload("gh pr merge 12 --squash")))
        self.configure("enforce")
        self.assertTrue(self.denied("action_authority_gate", self.payload("gh pr merge 12 --squash")))


if __name__ == "__main__":
    unittest.main()
