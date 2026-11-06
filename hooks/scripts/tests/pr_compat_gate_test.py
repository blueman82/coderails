#!/usr/bin/env python3
"""Keep the direct PR merge compatibility review gate on the current head."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.pr_merge_gate import merge_reason
from hooks.scripts.tests.lib.hook_test_support import HookTestCase
from scripts.lib.git_common import EvalSummary

MODULE = "hooks.scripts.lib.pr_merge_gate"


class CompatMergeEvidenceTests(HookTestCase):
    """A refusing compatibility line blocks the direct merge path."""

    def test_direct_merge_refuses_compat_findings(self) -> None:
        """The direct gh merge hook enforces the same review refusal as merge.py."""
        before = Path.cwd()
        self.addCleanup(os.chdir, before)
        with (
            patch(MODULE + ".pr_field", return_value="head"),
            patch(MODULE + ".gate_review_summary_for_pr", return_value=(3, "compat_findings_clean_break")),
            patch(MODULE + ".gate_eval_summary_for_pr", return_value=EvalSummary(0, "1", "{}", "")),
            patch(MODULE + ".smoke_verify", return_value=0),
            patch(MODULE + ".integrity_reason", return_value=""),
            patch(MODULE + ".publication_gate.evaluate", return_value=[]),
        ):
            self.assertIn("compat_findings_clean_break", merge_reason("1", str(self.directory)))

    def test_direct_merge_keeps_existing_review_invocation_contract(self) -> None:
        """An absent artifact is handled by the existing invocation gate; an invalid one is refused here."""
        before = Path.cwd()
        self.addCleanup(os.chdir, before)
        with (
            patch(MODULE + ".pr_field", return_value="head"),
            patch(MODULE + ".gate_review_summary_for_pr", return_value=(1, "")),
            patch(MODULE + ".gate_eval_summary_for_pr", return_value=EvalSummary(0, "1", "{}", "")),
            patch(MODULE + ".smoke_verify", return_value=0),
            patch(MODULE + ".integrity_reason", return_value=""),
            patch(MODULE + ".publication_gate.evaluate", return_value=[]),
        ):
            self.assertEqual(merge_reason("1", str(self.directory)), "")


if __name__ == "__main__":
    unittest.main()
