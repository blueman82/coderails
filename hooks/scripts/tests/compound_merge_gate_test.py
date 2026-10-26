"""A compound merge must not share one PR's evidence with another PR."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts import enforce_pr_workflow


class CompoundMergeTests(unittest.TestCase):
    """The hook handles one protected action per command."""

    def test_second_pr_cannot_use_first_pr_evidence(self) -> None:
        """Two PR merges are refused before any publication check runs."""
        payload = {
            "cwd": str(Path(__file__).resolve().parents[3]),
            "session_id": "test-session",
            "tool_input": {"command": "gh pr merge 1 --squash && gh pr merge 2 --squash"},
        }
        module = "hooks.scripts.enforce_pr_workflow"
        with (
            patch(module + ".read_payload_strict", return_value=payload),
            patch(module + ".publication_gate.enforce") as publication,
            patch(module + ".merge_reason") as evidence,
            patch(module + ".deny") as deny,
        ):
            enforce_pr_workflow.main()
            publication.assert_not_called()
            evidence.assert_not_called()
            self.assertIn("one protected action", deny.call_args.args[0])
