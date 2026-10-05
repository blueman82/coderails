"""verify_merged.py: one rule set for merge-commit and squash merges, content-first, ancestry only for true merges."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/verify_merged.py"
GH_SHIM = '#!/bin/sh\n[ "$1 $2" = "pr view" ] && cat "$FAKE_PR_JSON"\nexit 0\n'
OLD_RULE_ON_SQUASH = 1  # `git merge-base --is-ancestor <pr head> origin/main` on a squash merge: not an ancestor


def git(cwd: Path, *args: str) -> str:
    """Run git with a fixed identity and return stdout; the exit code is checked."""
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t"}
    env["GIT_COMMITTER_EMAIL"] = "t@t"
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


class VerifyMergedCase(unittest.TestCase):
    """A bare origin, a work clone, a fake gh and helpers to land a PR as a merge commit or a squash."""

    def setUp(self) -> None:
        """Create origin, clone, shim."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        git(root, "init", "-q", "--bare", "-b", "main", "origin.git")
        git(root, "clone", "-q", "origin.git", "work")
        self.work = root / "work"
        (self.work / "a.txt").write_text("base\n")
        git(self.work, "add", ".")
        git(self.work, "commit", "-q", "-m", "base")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        git(self.work, "switch", "-q", "-c", "feature")
        (self.work / "feat.txt").write_text("unique-change-token\n")
        git(self.work, "add", ".")
        git(self.work, "commit", "-q", "-m", "feature")
        self.head = git(self.work, "rev-parse", "HEAD")
        git(self.work, "switch", "-q", "main")
        shim = root / "bin/gh"
        shim.parent.mkdir()
        shim.write_text(GH_SHIM)
        shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
        self.pr_json = root / "pr.json"

    def land(self, squash: bool) -> str:
        """Merge the feature branch into origin/main as a squash commit or a true merge commit."""
        if squash:
            git(self.work, "merge", "--squash", "feature")
            git(self.work, "commit", "-q", "-m", "squash")
        else:
            git(self.work, "merge", "--no-ff", "-q", "-m", "merge", "feature")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        return git(self.work, "rev-parse", "HEAD")

    def verify(
        self, merge_commit: str, state: str = "MERGED", merged_at: str | None = "2026-10-01T00:00:00Z", *extra: str
    ) -> tuple[int, dict[str, Any]]:
        """Run the CLI against the fake PR and return (exit code, verdict)."""
        self.pr_json.write_text(
            json.dumps(
                {
                    "state": state,
                    "mergedAt": merged_at,
                    "mergeCommit": {"oid": merge_commit} if merge_commit else None,
                    "baseRefName": "main",
                    "headRefOid": self.head,
                }
            )
        )
        env = {
            **os.environ,
            "PATH": f"{self.pr_json.parent / 'bin'}:{os.environ['PATH']}",
            "FAKE_PR_JSON": str(self.pr_json),
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.pr_json.parent / "loops"),
        }
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "7", "--repo", str(self.work), *extra],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode, json.loads(result.stdout)


class VerifyMergedTests(VerifyMergedCase):
    """Both merge shapes verify by content; absence and wrong state do not."""

    def test_merge_commit_verifies_by_content_and_by_ancestry(self) -> None:
        """A true merge commit confirms with a grep; with no grep the two-parent ancestry is trusted."""
        merge_commit = self.land(squash=False)
        code, verdict = self.verify(
            merge_commit, "MERGED", "2026-10-01T00:00:00Z", "--grep", "unique-change-token", "--path", "feat.txt"
        )
        self.assertEqual((code, verdict["confirmed"], verdict["method"]), (0, True, "content"))
        code, verdict = self.verify(merge_commit)
        self.assertEqual((code, verdict["confirmed"], verdict["method"]), (0, True, "merge-commit-ancestry"))

    def test_squash_merge_is_confirmed_by_content_not_failed_for_missing_ancestry(self) -> None:
        """The PR head is not an ancestor of a squash merge; content confirms it and ancestry alone never does."""
        squash = self.land(squash=True)
        old_rule = subprocess.run(
            ["git", "merge-base", "--is-ancestor", self.head, "origin/main"], cwd=self.work
        ).returncode
        self.assertEqual(
            old_rule, OLD_RULE_ON_SQUASH
        )  # negative control: the old --is-ancestor rule would fail this PR
        code, verdict = self.verify(
            squash, "MERGED", "2026-10-01T00:00:00Z", "--grep", "unique-change-token", "--path", "feat.txt"
        )
        self.assertEqual((code, verdict["confirmed"], verdict["method"]), (0, True, "content"))
        code, verdict = self.verify(squash)
        self.assertEqual((code, verdict["confirmed"]), (1, False))
        self.assertIn("content_check_required", verdict["reasons"])

    def test_merged_state_without_the_content_is_not_confirmed(self) -> None:
        """State MERGED and a reachable merge commit do not confirm a change that is absent from origin/main."""
        merge_commit = self.land(squash=True)
        code, verdict = self.verify(
            merge_commit, "MERGED", "2026-10-01T00:00:00Z", "--grep", "no-such-token", "--path", "feat.txt"
        )
        self.assertEqual((code, verdict["confirmed"]), (1, False))
        self.assertIn("content_absent", verdict["reasons"])

    def test_needle_already_on_the_base_parent_is_not_proof_of_this_pr(self) -> None:
        """A string present before the PR (here `base`, in a.txt) must not confirm a MERGED PR."""
        for squash in (True, False):
            with self.subTest(squash=squash):
                self.setUp()
                merge_commit = self.land(squash=squash)
                code, verdict = self.verify(merge_commit, "MERGED", "2026-10-01T00:00:00Z", "--grep", "base")
                self.assertEqual((code, verdict["confirmed"]), (1, False))
                self.assertIn("content_preexisting", verdict["reasons"])

    def test_every_verdict_writes_one_trace_row(self) -> None:
        """Confirmed -> verify-merged/ok/verified; refused -> verify-merged/refused/<first reason>."""
        merge_commit = self.land(squash=True)
        self.verify(
            merge_commit, "MERGED", "2026-10-01T00:00:00Z", "--grep", "unique-change-token", "--path", "feat.txt"
        )
        self.verify(merge_commit, "MERGED", "2026-10-01T00:00:00Z", "--grep", "no-such-token")
        rows = [
            json.loads(line)
            for path in (self.pr_json.parent / "loops").glob("*/trace.jsonl")
            for line in path.read_text().splitlines()
        ]
        self.assertEqual(
            [(r["command"], r["outcome"], r["reason_code"]) for r in rows],
            [("verify-merged", "ok", "verified"), ("verify-merged", "refused", "content_absent")],
        )

    def test_state_and_reachability_refusals(self) -> None:
        """Open or not-merged PRs, a missing mergedAt and an unreachable merge commit are refused."""
        merge_commit = self.land(squash=True)
        for state, merged_at, commit, reason in (
            ("OPEN", None, merge_commit, "not_merged"),
            ("MERGED", None, merge_commit, "merged_at_missing"),
            ("MERGED", "2026-10-01T00:00:00Z", "0" * 40, "merge_commit_unreachable"),
        ):
            with self.subTest(reason=reason):
                code, verdict = self.verify(
                    commit, state, merged_at, "--grep", "unique-change-token", "--path", "feat.txt"
                )
                self.assertEqual((code, verdict["confirmed"]), (1, False))
                self.assertIn(reason, verdict["reasons"])


class SkillPairTests(unittest.TestCase):
    """The two skills no longer give opposite ancestry rules and both point at the script."""

    def test_no_opposite_ancestry_rules_and_both_call_the_script(self) -> None:
        """verify-merged-pr must not offer --is-ancestor as proof; phase 9 must not forbid what the other allows."""
        verify = (REPO / "skills/verify-merged-pr/SKILL.md").read_text()
        phase9 = (REPO / "skills/agentic-loop/phase-9-wiki-docs.md").read_text()
        codex = (REPO / "packages/codex/skills/verify-merged-pr/SKILL.md").read_text()
        for text in (verify, codex):
            self.assertIn("scripts/verify_merged.py", text)
            self.assertNotIn('&& echo "on origin', text)
        self.assertIn("scripts/verify_merged.py", phase9)
        self.assertNotIn("Do **not** confirm a merge with `git merge-base --is-ancestor", phase9)


if __name__ == "__main__":
    unittest.main()
