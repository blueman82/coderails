#!/usr/bin/env python3
"""Verify exact-head trusted eval and newest-machine-attestation failures remain blocking."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.pr_merge_gate import integrity_reason, merge_reason
from hooks.scripts.tests.lib.hook_test_support import HookTestCase
from scripts.lib.git_common import EvalSummary

MODULE = "hooks.scripts.lib.pr_merge_gate"


class MergeEvidenceTests(HookTestCase):
    """Fail-closed outputs distinguish API failures from rejected or absent trusted evidence."""

    def test_integrity_newest_exact_head_creator_state_and_description(self) -> None:
        """Only the newest successful configured-machine attestation can authorize this head."""
        sha = "a" * 40
        valid = {
            "state": "success",
            "creator": {"login": "github-actions[bot]"},
            "description": f"integrity=pass sha={sha}",
        }
        rows: list[object] = [
            [],
            [{**valid, "state": "pending"}],
            [{**valid, "creator": {"login": "other"}}],
            [{**valid, "description": f"integrity=pass sha={'b' * 40}"}],
            [{**valid, "description": f"integrity=passing sha={sha}"}],
            [{**valid, "description": f"integrity=pass sha={sha}0"}],
            [{**valid, "description": []}],
            [{**valid, "creator": None}],
            [{**valid, "state": "failure"}, valid],
            "malformed",
        ]
        config = self.directory / "workflow.config.yaml"
        config.write_text("integrity_review:\n  enabled: true\n")
        with (
            patch(MODULE + ".config_path", return_value=config),
            patch(MODULE + ".integrity_enabled", return_value=True),
            patch(MODULE + ".repo", return_value="owner/repo"),
        ):
            for row in rows:
                with (
                    patch(MODULE + ".run", return_value=subprocess.CompletedProcess([], 0, json.dumps(row))),
                    self.subTest(row=row),
                ):
                    self.assertTrue(integrity_reason("1", sha, str(self.directory)))
            with patch(MODULE + ".run", return_value=subprocess.CompletedProcess([], 0, json.dumps([valid]))):
                self.assertEqual(integrity_reason("1", sha, str(self.directory)), "")
            with patch(MODULE + ".run", return_value=subprocess.CompletedProcess([], 1, "")):
                self.assertIn("GitHub fetch failed", integrity_reason("1", sha, str(self.directory)))

    def test_legacy_integrity_hook_accepts_only_configured_login(self) -> None:
        """An old config keeps the same status author rule until enabled becomes true."""
        config = self.directory / "workflow.config.yaml"
        config.write_text("integrity_review:\n  machine_user: machine\n  enabled: false\n")
        sha = "a" * 40
        old = {"state": "success", "creator": {"login": "machine"}, "description": f"integrity=pass sha={sha}"}
        bot = {**old, "creator": {"login": "github-actions[bot]"}}
        with patch(MODULE + ".config_path", return_value=config), patch(MODULE + ".repo", return_value="owner/repo"):
            with patch(MODULE + ".run", return_value=subprocess.CompletedProcess([], 0, json.dumps([old]))):
                self.assertEqual(integrity_reason("1", sha, str(self.directory)), "")
            with patch(MODULE + ".run", return_value=subprocess.CompletedProcess([], 0, json.dumps([bot]))):
                self.assertTrue(integrity_reason("1", sha, str(self.directory)))
            config.write_text("integrity_review:\n  machine_user: machine\n  enabled: true\n")
            with patch(MODULE + ".run", return_value=subprocess.CompletedProcess([], 0, json.dumps([bot]))):
                self.assertEqual(integrity_reason("1", sha, str(self.directory)), "")

    def test_eval_failures_and_actual_smoke_gate_result_propagation(self) -> None:
        """Missing head, fetch failure, NO-GO, missing embeds and failed verification all deny."""
        before = Path.cwd()
        self.addCleanup(os.chdir, before)
        with patch(MODULE + ".pr_field", return_value="head"), patch(MODULE + ".integrity_reason", return_value=""):
            for summary in (
                EvalSummary(2, "", "", "identity"),
                EvalSummary(2, "", "", "permission"),
                EvalSummary(2, "", "", "comments"),
                EvalSummary(1, "", "", ""),
                EvalSummary(1, "1", "", ""),
                EvalSummary(0, "1", "", ""),
            ):
                with patch(MODULE + ".gate_eval_summary_for_pr", return_value=summary):
                    self.assertTrue(merge_reason("1", str(self.directory)))
            summary = EvalSummary(0, "1", '{"head_sha":"head","evals":[]}', "")
            with patch(MODULE + ".gate_eval_summary_for_pr", return_value=summary):
                for code in (0, 1):
                    with patch(MODULE + ".smoke_verify", return_value=code) as smoke:
                        reason = merge_reason("1", str(self.directory))
                        self.assertEqual(bool(reason), bool(code))
                        self.assertEqual(smoke.call_args.args[1], "head")
                        self.assertFalse(smoke.call_args.args[0].exists(), "temporary embed must be cleaned")
        with patch(MODULE + ".pr_field", return_value=""):
            self.assertIn("head SHA", merge_reason("1", str(self.directory)))
        self.assertIn("valid repo", merge_reason("1", str(self.directory / "missing")))


if __name__ == "__main__":
    unittest.main()
