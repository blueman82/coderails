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
from hooks.scripts import enforce_pr_workflow
from hooks.scripts.lib.pr_merge_gate import integrity_reason, merge_reason
from hooks.scripts.tests.lib.hook_test_support import HookTestCase
from scripts.lib.git_common import EvalSummary

MODULE = "hooks.scripts.lib.pr_merge_gate"


class MergeEvidenceTests(HookTestCase):
    """Fail-closed outputs distinguish API failures from rejected or absent trusted evidence."""

    def test_integrity_newest_exact_head_creator_state_and_description(self) -> None:
        """Only the newest successful configured-machine attestation can authorize this head."""
        sha = "a" * 40
        valid = {"state": "success", "creator": {"login": "machine"}, "description": f"integrity=pass sha={sha}"}
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
        with (
            patch(MODULE + ".config_path", return_value="config"),
            patch(MODULE + ".integrity_machine_user", return_value="machine"),
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

    def test_eval_failures_and_actual_smoke_gate_result_propagation(self) -> None:
        """Missing head, fetch failure, NO-GO, missing embeds and failed verification all deny."""
        before = Path.cwd()
        self.addCleanup(os.chdir, before)
        with (
            patch(MODULE + ".pr_field", return_value="head"),
            patch(MODULE + ".integrity_reason", return_value=""),
            patch(MODULE + ".publication_gate.evaluate", return_value=[]),
        ):
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

    def test_target_is_parsed_not_guessed(self) -> None:
        """Claude arm: a flag value is not the PR, and an unresolvable target denies instead of using this branch."""
        from hooks.scripts.lib.pr_workflow_match import pr_number

        self.assertEqual(pr_number("gh pr merge --body 1 42"), "42")
        self.assertEqual(pr_number("gh pr merge --repo o/r 42"), "?")
        before = Path.cwd()
        self.addCleanup(os.chdir, before)
        with patch("scripts.lib.git_common.pr_num", return_value="9"):
            self.assertIn("could not resolve a PR number", merge_reason("?", str(self.directory)))

    def test_review_prerequisite_uses_resolved_number(self) -> None:
        """A reviewed PR can be selected by branch or URL without changing its prerequisite."""
        before = Path.cwd()
        self.addCleanup(os.chdir, before)
        module = "hooks.scripts.enforce_pr_workflow"
        for target in ("feature", "https://github.com/o/r/pull/42"):
            payload = {
                "cwd": str(self.directory),
                "transcript_path": __file__,
                "tool_input": {"command": f"gh pr merge {target}"},
            }
            with (
                patch(module + ".read_payload_strict", return_value=payload),
                patch(module + ".config_path", return_value="config"),
                patch(module + ".transcript_entries", return_value=[]),
                patch(module + ".merge_target.resolve", return_value="42"),
                patch(module + ".git.pr_field", return_value="head"),
                patch(module + ".publication_gate.evaluate", return_value=[]),
                patch(module + ".step_found", return_value=True) as prerequisite,
                patch(module + ".merge_reason", return_value=""),
                patch(module + ".deny") as deny,
            ):
                enforce_pr_workflow.main()
                prerequisite.assert_called_once_with([], "merge", "42")
                deny.assert_not_called()

    def test_scope_and_effective_directory_reach_the_merge_gate(self) -> None:
        """Plain, wrapped and chained merges carry their unit scope and actual directory."""
        before = Path.cwd()
        self.addCleanup(os.chdir, before)
        module = "hooks.scripts.enforce_pr_workflow"
        directory = str(self.directory)
        command = "python3 scripts/merge.py 42 --unit 2 --progress p.json"
        for text, cwd in (
            (command, directory),
            (f"bash -c '{command}'", directory),
            (f"cd {directory} && {command}", str(self.directory.parent)),
            (f"cd {directory} && bash -c '{command}'", str(self.directory.parent)),
        ):
            payload = {"cwd": cwd, "transcript_path": __file__, "tool_input": {"command": text}}
            with (
                self.subTest(command=text),
                patch(module + ".read_payload_strict", return_value=payload),
                patch(module + ".config_path", return_value="config"),
                patch(module + ".transcript_entries", return_value=[]),
                patch(module + ".git.pr_field", return_value="head"),
                patch(module + ".publication_gate.evaluate", return_value=[]),
                patch(module + ".step_found", return_value=True),
                patch(module + ".merge_reason", return_value="") as gate,
            ):
                enforce_pr_workflow.main()
                gate.assert_called_once_with("42", directory, unit="2", progress="p.json")

    def test_gh_repo_retarget_denies_before_evidence_lookup(self) -> None:
        """A merge retargeted by GH_REPO cannot borrow this repository's review and eval evidence."""
        module = "hooks.scripts.enforce_pr_workflow"
        payload = {
            "cwd": str(self.directory),
            "transcript_path": __file__,
            "tool_input": {"command": "GH_REPO=other/repo gh pr merge 42"},
        }
        with (
            patch(module + ".read_payload_strict", return_value=payload),
            patch(module + ".config_path", return_value="config"),
            patch(module + ".transcript_entries", return_value=[]),
            patch(module + ".step_found", return_value=True),
            patch(module + ".merge_reason") as gate,
            patch(module + ".deny") as deny,
        ):
            enforce_pr_workflow.main()
            gate.assert_not_called()
            self.assertTrue(deny.call_args.args[0].startswith("pr_repo_override:"))

    def test_direct_publication_check_needs_no_config_or_transcript(self) -> None:
        """Default-on manifest checks reach a direct merge even without the advisory workflow setup."""
        before = Path.cwd()
        self.addCleanup(os.chdir, before)
        module = "hooks.scripts.enforce_pr_workflow"
        payload = {"cwd": str(self.directory), "tool_input": {"command": "gh pr merge 42"}}
        with (
            patch(module + ".read_payload_strict", return_value=payload),
            patch(module + ".config_path", return_value=""),
            patch(module + ".merge_target.resolve", return_value="42"),
            patch("scripts.lib.git_common.pr_field", return_value="a" * 40),
            patch(
                "scripts.lib.publication_gate.evaluate",
                return_value=[{"code": "diff_manifest:denied_path", "detail": "x"}],
            ) as gate,
            patch(module + ".deny") as deny,
        ):
            enforce_pr_workflow.main()
            gate.assert_called_once_with("42", "a" * 40, "", "")
            self.assertTrue(deny.call_args.args[0].startswith("diff_manifest:denied_path"))

    def test_base_edit_then_merge_refuses_before_publication_lookup(self) -> None:
        """One Bash call cannot retarget the PR base after the hook checks its old base."""
        before = Path.cwd()
        self.addCleanup(os.chdir, before)
        module = "hooks.scripts.enforce_pr_workflow"
        payload = {
            "cwd": str(self.directory),
            "tool_input": {"command": "gh pr edit 42 --base old-release && gh pr merge 42"},
        }
        with (
            patch(module + ".read_payload_strict", return_value=payload),
            patch(module + ".publication_gate.evaluate") as gate,
            patch(module + ".deny") as deny,
        ):
            enforce_pr_workflow.main()
            gate.assert_not_called()
            self.assertTrue(deny.call_args.args[0].startswith("pr_base_mutation:"))

        payload = {
            "cwd": str(self.directory),
            "tool_input": {
                "command": 'gh api "repos/o/r/pulls/42" -X PATCH --input /tmp/base-change.json && gh pr merge 42'
            },
        }
        with (
            patch(module + ".read_payload_strict", return_value=payload),
            patch(module + ".publication_gate.evaluate") as gate,
            patch(module + ".deny") as deny,
        ):
            enforce_pr_workflow.main()
            gate.assert_not_called()
            self.assertTrue(deny.call_args.args[0].startswith("pr_base_mutation:"))

        payload = {
            "cwd": str(self.directory),
            "tool_input": {
                "command": "gh api -X PATCH repos/o/r/pulls/42 --input /tmp/base-change.json && gh pr merge 42"
            },
        }
        with (
            patch(module + ".read_payload_strict", return_value=payload),
            patch(module + ".publication_gate.evaluate") as gate,
            patch(module + ".deny") as deny,
        ):
            enforce_pr_workflow.main()
            gate.assert_not_called()
            self.assertTrue(deny.call_args.args[0].startswith("pr_base_mutation:"))

        payload = {
            "cwd": str(self.directory),
            "tool_input": {"command": "gh api -X PATCH repos/o/r/pulls/42 -f base=old-release && gh pr merge 42"},
        }
        with (
            patch(module + ".read_payload_strict", return_value=payload),
            patch(module + ".publication_gate.evaluate") as gate,
            patch(module + ".deny") as deny,
        ):
            enforce_pr_workflow.main()
            gate.assert_not_called()
            self.assertTrue(deny.call_args.args[0].startswith("pr_base_mutation:"))

    def test_body_flag_values_are_not_no_ops(self) -> None:
        """Consumed body values remain guarded; actual help and dry-run options are harmless."""
        from hooks.scripts.lib.pr_workflow_match import guarded_segments

        for value in ("--help", "--dry-run"):
            for option in (f"--body '{value}'", f"--body={value}", f"--subject '{value}'"):
                command = f"gh pr merge 42 {option} --merge"
                with self.subTest(command=command):
                    self.assertEqual(
                        guarded_segments(command, str(self.directory)), [("merge", command, str(self.directory))]
                    )
            self.assertEqual(guarded_segments(f"gh pr merge 42 {value}", str(self.directory)), [])

    def test_api_merge_with_leading_options_is_guarded(self) -> None:
        """A valid API merge keeps its gate when method options precede the endpoint."""
        from hooks.scripts.lib.pr_workflow_match import guarded_segments

        command = "gh api -X PUT repos/o/r/pulls/42/merge"
        self.assertEqual(guarded_segments(command, str(self.directory)), [("merge", command, str(self.directory))])
        unrelated = "gh api -f note=repos/o/r/pulls/42/merge repos/o/r/issues/42"
        self.assertEqual(guarded_segments(unrelated, str(self.directory)), [])

    def test_lifecycle_body_values_are_guarded(self) -> None:
        """Git lifecycle text in an option value cannot exempt a PR merge."""
        from hooks.scripts.lib.pr_workflow_match import guarded_segments, operation

        for flag in ("--abort", "--continue", "--quit", "--skip"):
            command = f"gh pr merge 42 --body 'git merge {flag}' --merge"
            with self.subTest(flag=flag):
                self.assertEqual(
                    guarded_segments(command, str(self.directory)), [("merge", command, str(self.directory))]
                )
                self.assertEqual(operation(f"git merge {flag}"), ("", "", ""))

    def test_subshell_restores_cwd_and_braces_retain_it(self) -> None:
        """Parentheses localize cd, including cd-only and wrapped groups; braces share it."""
        from hooks.scripts.lib.pr_workflow_match import guarded_segments

        cwd, other = str(self.directory), str(self.directory / "other")
        for prefix in (f"(cd {other} && gh pr merge 42)", f"(cd {other} && bash -c 'gh pr merge 42')"):
            with self.subTest(prefix=prefix):
                self.assertEqual(
                    guarded_segments(prefix + "; gh pr merge 43", cwd),
                    [("merge", "gh pr merge 42", other), ("merge", "gh pr merge 43", cwd)],
                )
        self.assertEqual(guarded_segments(f"(cd {other}); gh pr merge 43", cwd), [("merge", "gh pr merge 43", cwd)])
        self.assertEqual(
            guarded_segments(f"{{ cd {other} && gh pr merge 42; }}; gh pr merge 43", cwd),
            [("merge", "gh pr merge 42", other), ("merge", "gh pr merge 43", other)],
        )

    def test_publication_gate_violation_denies_with_code_first(self) -> None:
        """Direct Claude path: a publication violation denies, reason code first; no violation passes."""
        before = Path.cwd()
        self.addCleanup(os.chdir, before)
        summary = EvalSummary(0, "1", '{"head_sha":"head","evals":[]}', "")
        violation = [{"code": "diff_manifest:denied_path", "detail": "secret"}]
        with (
            patch(MODULE + ".pr_field", return_value="head"),
            patch(MODULE + ".gate_eval_summary_for_pr", return_value=summary),
            patch(MODULE + ".smoke_verify", return_value=0),
            patch(MODULE + ".integrity_reason", return_value=""),
        ):
            with patch(MODULE + ".publication_gate.evaluate", return_value=violation) as evaluate:
                reason = merge_reason("1", str(self.directory))
            self.assertTrue(reason.startswith("diff_manifest:denied_path"), reason)
            self.assertIn("gh pr merge 1", reason)
            self.assertEqual(evaluate.call_args.args[:2], ("1", "head"))
            with patch(MODULE + ".publication_gate.evaluate", return_value=[]):
                self.assertEqual(merge_reason("1", str(self.directory)), "")


if __name__ == "__main__":
    unittest.main()
