"""Preserve merge gate ordering, refusal diagnostics and nonfatal cleanup contracts."""

from __future__ import annotations

import io
import subprocess
import sys
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts import merge
from scripts.lib import git_common as git


class MergeContractTests(unittest.TestCase):
    """Intercept every external operation; no test can contact GitHub or modify Git."""

    def invoke(
        self,
        *,
        review: tuple[int, str] = (0, ""),
        summary: git.EvalSummary | None = None,
        sha: str = "deadbeef",
        smoke: int = 0,
        state: str = "OPEN",
        temporary_failure: bool = False,
    ) -> tuple[int, str, bool, bool]:
        """Run the real merge entrypoint over controlled provider and evidence replies."""
        if summary is None:
            summary = git.EvalSummary(0, "0", "{}")
        merged: list[tuple[str, ...]] = []

        def command(*arguments: str, check: bool = False) -> subprocess.CompletedProcess[str]:
            """Record only a simulated remote merge, returning inert command output."""
            del check
            if arguments[:3] == ("gh", "pr", "merge"):
                merged.append(arguments)
            return subprocess.CompletedProcess(arguments, 0, "", "")

        def field(number: str, name: str, fallback: str = "") -> str:
            """Return exact-head fields without using a provider CLI."""
            del number
            return {"headRefOid": sha, "state": state, "title": "fixture", "headRefName": "feature"}.get(name, fallback)

        stream = io.StringIO()
        with ExitStack() as stack:
            for name, value in {
                "require_repo": None,
                "main": "main",
                "branch": "feature",
                "pr_num": "7",
                "protected": False,
                "sync_main_branch": None,
                "output": "",
            }.items():
                stack.enter_context(patch.object(git, name, return_value=value))
            stack.enter_context(patch.object(git, "pr_field", side_effect=field))
            stack.enter_context(patch.object(git, "run", side_effect=command))
            stack.enter_context(patch.object(git, "gate_review_summary_for_pr", return_value=review))
            eval_reader = stack.enter_context(patch.object(git, "gate_eval_summary_for_pr", return_value=summary))
            stack.enter_context(patch.object(merge, "smoke_verify", return_value=smoke))
            stack.enter_context(patch.object(merge, "config_path", return_value=""))
            stack.enter_context(patch.object(merge, "has_wiki_ingest_for_merged_prs"))
            if temporary_failure:
                stack.enter_context(
                    patch(
                        "scripts.merge.tempfile.TemporaryDirectory", side_effect=OSError("fixture allocation refused")
                    )
                )
            with redirect_stdout(stream), redirect_stderr(stream):
                code = merge.main(["7"])
            return code, stream.getvalue(), bool(merged), bool(eval_reader.called)

    def test_review_and_head_refusals_precede_every_later_gate(self) -> None:
        """Missing/stale review and unavailable head must refuse without evaluating or merging."""
        for review, sha, expected in (((1, ""), "deadbeef", "post-review"), ((0, ""), "", "GitHub fetch")):
            code, text, merged, eval_called = self.invoke(review=review, sha=sha)
            self.assertEqual(code, 1)
            self.assertIn(expected, text)
            self.assertFalse(merged)
            self.assertFalse(eval_called)
        code, _, merged, eval_called = self.invoke()
        self.assertEqual(code, 0)
        self.assertTrue(merged)
        self.assertTrue(eval_called)

    def test_fetch_diagnostics_distinguish_identity_permission_and_local_failure(self) -> None:
        """Name each trust-failure stage without relabelling local failures as network errors."""
        for stage, expected in (
            ("identity", "authenticated identity"),
            ("permission", "repo permission"),
            ("", "GitHub fetch"),
            ("tempfile", "temporary file"),
        ):
            for eval_gate in (False, True):
                outcome = (
                    self.invoke(summary=git.EvalSummary(2, failure_reason=stage))
                    if eval_gate
                    else self.invoke(review=(2, stage))
                )
                code, text, merged, _ = outcome
                self.assertEqual(code, 1)
                self.assertIn(expected, text)
                self.assertFalse(merged)
                if eval_gate:
                    self.assertIn("eval artifact", text)

    def test_absent_and_no_go_evals_keep_distinct_author_actions(self) -> None:
        """Explain absent evidence separately from a recorded NO-GO at either level."""
        for level in ("", "0", "1"):
            code, text, merged, _ = self.invoke(summary=git.EvalSummary(1, level))
            self.assertEqual(code, 1)
            self.assertFalse(merged)
            self.assertIn("deadbeef", text)
            if level:
                self.assertIn("NO-GO", text)
                self.assertIn(f"verification_level {level}", text)
            else:
                self.assertIn("No coderails eval artifact", text)

    def test_smoke_and_temporary_failure_never_merge(self) -> None:
        """Live re-execution and its local scratch allocation both remain fail-closed."""
        code, text, merged, _ = self.invoke(smoke=1)
        self.assertEqual(code, 1)
        self.assertIn("Smoke-verify", text)
        self.assertIn("deadbeef", text)
        self.assertFalse(merged)
        code, text, merged, _ = self.invoke(temporary_failure=True)
        self.assertEqual(code, 1)
        self.assertIn("temporary file", text)
        self.assertFalse(merged)

    def test_closed_unknown_and_already_merged_states(self) -> None:
        """Only an open fully gated PR produces a new remote merge operation."""
        for state in ("CLOSED", "UNKNOWN", "MERGED"):
            code, _, merged, evaluated = self.invoke(state=state)
            self.assertEqual(code, 0 if state == "MERGED" else 1)
            self.assertFalse(merged)
            self.assertFalse(evaluated)


if __name__ == "__main__":
    unittest.main()
