"""Codex eval level: hook enforces the derived minimum and suite integrity, post_evals.py post works, mirrors agree."""

from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast

# Not importing scripts.*: that would bind the root `scripts` package and break the Codex tests that need
# packages/codex/scripts under the same name. Everything below runs the Codex files as subprocesses.
ROOT = Path(__file__).resolve().parents[2]
CODEX = ROOT / "packages/codex"
sys.path.insert(0, str(ROOT))
from packages.tests.eval_artifact_fixture import suite_hash, write_comment  # noqa: E402

HOOK = CODEX / "hooks/scripts/pr_publication_gate.py"
POST = CODEX / "scripts/post_evals.py"
HOOK_SHIM = """#!/bin/sh
case "$1 $2" in
  "pr view")
    [ "$5" = headRefOid ] && echo "$FAKE_SHA"
    [ "$5" = baseRefOid ] && echo "$FAKE_BASE_SHA" ;;
  "api user") echo me ;;
  "repo view") echo WRITE ;;
  "api repos/"*)
    { printf '<!-- coderails-review-summary v1 pr=7 head_sha=%s -->\\n' "$FAKE_SHA"; echo '## No findings'; } \\
      | base64 | tr -d '\\n'
    echo
    [ -n "$FAKE_EVAL_FILE" ] && { base64 < "$FAKE_EVAL_FILE" | tr -d '\\n'; echo; }
    ;;
esac
exit 0
"""
POST_SHIM = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(" ".join(a) + "\\n")
if a[:2] == ["pr", "view"]:
    print(os.environ["FAKE_BASE_SHA"] if "baseRefOid" in a else os.environ["FAKE_SHA"])
elif a[:2] == ["api", "user"]:
    print("me")
elif a[0] == "api" and "-F" in a:
    open(os.environ["FAKE_POSTED"], "w").write(open(a[a.index("-F") + 1].removeprefix("body=@")).read())
    print(json.dumps({"url": "https://github.com/o/r/pull/7#c1"}))
"""
MIRRORED = (
    "policy/surface_policy.json",
    "scripts/lib/eval_level.py",
    "scripts/lib/eval_validation.py",
    "scripts/lib/eval_artifact.py",
    "scripts/lib/publication_gate.py",
    "scripts/lib/git_common.py",
    "scripts/post_evals.py",
)


def git_cmd(cwd: Path, *args: str) -> str:
    """Run Git in a temp repo with a fixed identity."""
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t"}
    env |= {"GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


def shim(directory: Path, body: str) -> Path:
    """Install an executable fake gh in directory/bin and return that bin directory."""
    bin_dir = directory / "bin"
    bin_dir.mkdir(exist_ok=True)
    path = bin_dir / "gh"
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return bin_dir


class Repo(unittest.TestCase):
    """origin/main plus one feature commit touching `touched`, with a GitHub-looking remote."""

    touched = "install.py"

    def setUp(self) -> None:
        """Base commit on origin/main, then one feature commit."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)
        self.dir = self.tmp / "repo"
        self.dir.mkdir()
        git_cmd(self.dir, "init", "-q", "-b", "main")
        (self.dir / "README.md").write_text("doc\n")
        git_cmd(self.dir, "add", "-A")
        git_cmd(self.dir, "commit", "-qm", "base")
        self.base = git_cmd(self.dir, "rev-parse", "HEAD").strip()
        git_cmd(self.dir, "update-ref", "refs/remotes/origin/main", "HEAD")
        git_cmd(self.dir, "checkout", "-qb", "feature/x")
        git_cmd(self.dir, "remote", "add", "origin", "https://github.com/o/r.git")
        git_cmd(self.dir, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        target = self.dir / self.touched
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x = 1\n")
        git_cmd(self.dir, "add", "-A")
        git_cmd(self.dir, "commit", "-qm", "change")
        self.sha = git_cmd(self.dir, "rev-parse", "HEAD").strip()


class HookRepo(Repo):
    """Runs the Codex hook, as Codex does, over a fake gh that serves the review and eval artifacts."""

    def reason(self, **comment: object) -> str:
        """Permission-decision reason for `gh pr merge 7` given the eval comment, or empty when allowed."""
        (self.dir / ".coderails").mkdir(exist_ok=True)
        (self.dir / ".coderails/workflow.config.yaml").write_text(
            "review_passes: off\nevals:\n  require_signatures: false\n"
        )  # this test isolates eval-level behavior
        comment.setdefault("frozen_sha", self.base)
        eval_file = write_comment(self.tmp, self.sha, **comment)  # type: ignore[arg-type]
        env = {**os.environ, "PATH": f"{shim(self.tmp, HOOK_SHIM)}{os.pathsep}{os.environ['PATH']}"}
        env |= {
            "FAKE_SHA": self.sha,
            "FAKE_BASE_SHA": self.base,
            "FAKE_EVAL_FILE": str(eval_file),
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.tmp),
            "CODERAILS_AGENTIC_LOOP_DIR": str(self.tmp),
        }
        payload = {"session_id": "s", "cwd": str(self.dir), "tool_name": "Bash"}
        payload["tool_input"] = {"command": "gh pr merge 7"}  # type: ignore[assignment]
        result = subprocess.run(
            [sys.executable, str(HOOK)], input=json.dumps(payload), text=True, capture_output=True, env=env
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = cast(dict[str, dict[str, str]], json.loads(result.stdout)) if result.stdout.strip() else {}
        return output.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


class HookTests(HookRepo):
    """The hook applies the derived level and suite integrity."""

    def test_install_py_below_derived_is_denied(self) -> None:
        """Acceptance 1: install.py at level 0 and 1 is denied with the code first and the re-post remedy."""
        for level in (0, 1):
            with self.subTest(level=level):
                reason = self.reason(level=level)
                self.assertTrue(reason.startswith("level_below_derived"), reason)
                self.assertIn("post_evals.py post", reason)
        git_cmd(self.dir, "update-ref", "refs/remotes/origin/main", self.sha)
        self.assertTrue(self.reason(level=0).startswith("level_below_derived"))

    def test_install_py_at_level_two_proceeds(self) -> None:
        """Negative control 1: the same hook call allows at level 2, so the denial came from the derived level."""
        self.assertEqual(self.reason(level=2), "")

    def test_late_freeze_must_be_stamped(self) -> None:
        """Acceptance 3: a freeze on the branch whose facts line says late_freeze=0 is denied; stamped 1 proceeds."""
        self.assertTrue(self.reason(level=2, frozen_sha=self.sha).startswith("late_freeze_unstamped"))
        self.assertEqual(self.reason(level=2, frozen_sha=self.sha, late=True), "")
        self.assertEqual(self.reason(level=2, frozen_sha=self.base), "")  # on-time freeze, stamped 0

    def test_oracle_edit_is_denied(self) -> None:
        """Acceptance 2: an eval added to the embed after the freeze hash is a suite_hash_mismatch."""
        self.assertTrue(self.reason(level=2, tamper=True).startswith("suite_hash_mismatch"))


class DocsOnlyTests(HookRepo):
    """Docs never force a level."""

    touched = "docs/a.md"

    def test_docs_only_at_level_zero_proceeds(self) -> None:
        """Negative control 5: a docs-only PR at level 0 is allowed through the Codex hook."""
        self.assertEqual(self.reason(level=0), "")


class PostTests(Repo):
    """The Codex post_evals.py post: argument gate, derived-level refusal, body shape."""

    def smoke_run(self, level: int) -> Path:
        """A frozen suite for the current head, written and smoke-run exactly as the workflow does."""
        py = shlex.quote(sys.executable)
        evals = []
        if level:
            evals = [
                {
                    "id": "E1", "priority": "P0", "mode": "scripted", "status": "pass", "evidence": "observed",
                    "cmd": f"{py} -c 'print(1)'", "negative_control": f"{py} -c 'raise SystemExit(1)'",
                }
            ]  # fmt: skip
        path = self.dir / "evals.json"
        path.write_text(
            json.dumps(
                {
                    "verification_level": level, "verification_justification": "fixture", "head_sha": self.sha,
                    "frozen_sha": self.base, "task_ref": "1", "evals": evals,
                }
            )  # fmt: skip
        )
        env = {**os.environ, "CODERAILS_KEYS_DIR": str(self.tmp / "keys")}
        command = [sys.executable, str(POST), "smoke-run", str(path)]
        done = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return path

    def post(self, *arguments: str) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
        """Run `post_evals.py post ...` against a fake gh; returns (result, gh call log, posted body)."""
        log, posted = self.tmp / "gh.log", self.tmp / "posted.md"
        log.write_text("")
        env = {**os.environ, "PATH": f"{shim(self.tmp, POST_SHIM)}{os.pathsep}{os.environ['PATH']}"}
        env |= {"FAKE_SHA": self.sha, "FAKE_BASE_SHA": self.base, "FAKE_LOG": str(log), "FAKE_POSTED": str(posted)}
        env["CODERAILS_KEYS_DIR"] = str(self.tmp / "keys")
        result = subprocess.run(
            [sys.executable, str(POST), "post", *arguments], cwd=self.dir, env=env, capture_output=True, text=True
        )
        return result, log, posted

    def test_install_py_at_level_zero_posts_nothing(self) -> None:
        """Acceptance 1: level_below_derived, and no POST reached gh."""
        result, log, posted = self.post("7", str(self.smoke_run(0)))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("level_below_derived", result.stderr)
        self.assertFalse(posted.exists())
        self.assertNotIn("-F", log.read_text())
        git_cmd(self.dir, "update-ref", "refs/remotes/origin/main", self.sha)
        result, log, posted = self.post("7", str(self.dir / "evals.json"))
        self.assertIn("level_below_derived", result.stderr)
        self.assertFalse(posted.exists())
        self.assertNotIn("-F", log.read_text())

    def test_install_py_at_level_two_posts_marker_then_facts(self) -> None:
        """Negative control 1 and acceptance 4: line 1 is the unchanged v1 marker, line 2 the facts line."""
        result, _, posted = self.post("7", str(self.smoke_run(2)))
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = posted.read_text().splitlines()
        self.assertEqual(
            lines[0], f"<!-- coderails-eval-summary v1 pr=7 head_sha={self.sha} result=GO verification_level=2 -->"
        )
        embed = json.loads(posted.read_text().split("```json\n")[1].split("\n```")[0])
        self.assertTrue(lines[1].startswith("<!-- coderails-eval-facts v1 derived_min_level=2 late_freeze=0 suite="))
        self.assertTrue(lines[1].endswith(embed["gate_facts"]["suite_hash"][:16] + " -->"))
        self.assertEqual(embed["gate_facts"]["surfaces"], ["irreversible"])

    def test_invalid_number_makes_no_gh_call(self) -> None:
        """Acceptance 5: injection-shaped numbers fail with pr_number_invalid and the gh shim is never run."""
        suite = self.dir / "evals.json"
        suite.write_text("{}")
        for bad in ("7; id", "$(id)", "-1", "0"):
            with self.subTest(bad=bad):
                result, log, _ = self.post(bad, str(suite))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("pr_number_invalid", result.stderr)
                self.assertEqual(log.read_text(), "")


class MirrorTests(unittest.TestCase):
    """Policy and library copies are byte-identical; the Codex doc reduces to the call."""

    def test_copies_are_byte_identical(self) -> None:
        """Mirrored files must not drift between the Claude root and the Codex package."""
        for name in MIRRORED:
            with self.subTest(name=name):
                self.assertEqual((ROOT / name).read_bytes(), (CODEX / name).read_bytes())

    def test_codex_doc_has_no_arguments_recipe(self) -> None:
        """Acceptance 5: no $ARGUMENTS shell recipe in either post-evals doc."""
        for doc in ("commands/post-evals.md", "packages/codex/skills/post-evals/SKILL.md"):
            self.assertNotIn("$ARGUMENTS", (ROOT / doc).read_text())

    def test_hash_helper_matches_the_product(self) -> None:
        """The independent suite-hash definition used above equals scripts.lib.eval_integrity.suite_hash."""
        done = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]);"
                "from scripts.lib.eval_integrity import suite_hash;"
                "print(suite_hash({'verification_level': 2, 'task_ref': '1', 'evals': []}))",
                str(CODEX),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(done.stdout.strip(), suite_hash(2, []))


if __name__ == "__main__":
    unittest.main()
