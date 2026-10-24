"""Live authority still limits advisory receipt mode."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.receipt_hook_case import MERGE, ReceiptHookCase


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


if __name__ == "__main__":
    unittest.main()
