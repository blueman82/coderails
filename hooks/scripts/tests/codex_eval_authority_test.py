"""Keep PR evidence authority tied to fetched comments and the current head."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts import merge
from scripts.lib import git_common as git

ROOT = Path(__file__).resolve().parents[3]


class EvalAuthorityTests(unittest.TestCase):
    """Preserve the documented authority rule and exercise its execution boundary."""

    def test_native_skill_requires_remote_current_head_evidence(self) -> None:
        """Skill readers must not accept local eval JSON as PR readiness evidence."""
        post = (ROOT / "packages/codex/skills/post-evals/SKILL.md").read_text()
        task = (ROOT / "packages/codex/skills/task-evals/SKILL.md").read_text()
        for text in (
            "Local or committed eval files are working material, not PR-readiness evidence.",
            "Fetch the current head with `gh pr view <pr> --json headRefOid -q .headRefOid`.",
            "The marker must remain bound to the validated pull request and its currently fetched head.",
            "Never treat missing, stale, mismatched, rejected, untrusted, or unavailable evidence as success.",
        ):
            with self.subTest(contract=text):
                self.assertIn(text, post)
        self.assertIn(
            "PR scope** → the file is working material only. The durable artifact is the SHA-bound PR comment", task
        )

    def test_only_trusted_embed_executes_at_fetched_head(self) -> None:
        """Pass the fetched head and exact remote embed into the actual smoke boundary."""
        observed: list[tuple[str, str]] = []

        def execute(path: Path, head: str) -> int:
            """Observe the execution input without contacting GitHub or executing commands."""
            observed.append((path.read_text(), head))
            return 0

        with (
            patch.object(git, "pr_field", return_value="current-head") as fetch,
            patch.object(git, "gate_review_summary_for_pr", return_value=(0, "")),
            patch.object(
                git, "gate_eval_summary_for_pr", return_value=git.EvalSummary(0, "2", '{"remote":true}')
            ) as gate,
            patch.object(merge, "smoke_verify", side_effect=execute),
            patch.object(merge, "config_path", return_value=""),
            patch.object(merge, "has_wiki_ingest_for_merged_prs"),
        ):
            merge.verify_gates("42")
        fetch.assert_called_once_with("42", "headRefOid")
        gate.assert_called_once_with("42", "current-head")
        self.assertEqual(observed, [('{"remote":true}', "current-head")])

    def test_missing_untrusted_and_failed_smoke_refuse(self) -> None:
        """Absent or unavailable authority and failed re-execution cannot pass."""
        for status, smoke_code in ((1, 0), (2, 0), (0, 1)):
            with (
                self.subTest(status=status, smoke_code=smoke_code),
                patch.object(git, "pr_field", return_value="current-head"),
                patch.object(git, "gate_review_summary_for_pr", return_value=(0, "")),
                patch.object(
                    git, "gate_eval_summary_for_pr", return_value=git.EvalSummary(status, "2", "{}", "fetch failed")
                ),
                patch.object(merge, "smoke_verify", return_value=smoke_code) as smoke,
                self.assertRaises(git.WorkflowError),
            ):
                merge.verify_gates("42")
            self.assertEqual(smoke.call_count, int(status == 0))


if __name__ == "__main__":
    unittest.main()
