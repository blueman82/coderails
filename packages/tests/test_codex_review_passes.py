"""Codex review passes: the hook enforces required reviewers, post_review.py post works, and the mirrors agree."""

from __future__ import annotations

import hashlib
import json
import os
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
from packages.tests.eval_artifact_fixture import write_comment  # noqa: E402

HOOK = CODEX / "hooks/scripts/pr_publication_gate.py"
POST = CODEX / "scripts/post_review.py"
CLEAN = "## No findings\n"
CRITICAL = "## Critical\n- injection\n\n## Important\nNone\n\n## Suggestions\nNone\n"
ZERO = "0" * 64
HOOK_SHIM = """#!/bin/sh
case "$1 $2" in
  "pr view") [ "$5" = headRefOid ] && echo "$FAKE_SHA" ;;
  "api user") echo me ;;
  "repo view") echo WRITE ;;
  "api repos/"*)
    [ -n "$FAKE_NO_ARTIFACT" ] && exit 0
    { printf '<!-- coderails-review-summary v1 pr=7 head_sha=%s -->\\n' "$FAKE_SHA"
      [ -n "$FAKE_PASSES" ] && printf '<!-- coderails-review-passes v1 {"head_sha": "%s", "passes": %s} -->\\n' \\
        "${FAKE_PASSES_SHA:-$FAKE_SHA}" "$FAKE_PASSES"
      printf '%s\\n' "${FAKE_TAIL:-## No findings}"; } | base64 | tr -d '\\n'
    echo
    [ -n "$FAKE_EVAL_FILE" ] && { base64 < "$FAKE_EVAL_FILE" | tr -d '\\n'; echo; }
    ;;
esac
exit 0
"""
POST_SHIM = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
log_path = os.environ["FAKE_LOG"]
previous = [json.loads(line) for line in open(log_path).read().splitlines()]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(a) + "\\n")
if a[:2] == ["pr", "view"]:
    heads = json.loads(os.environ["FAKE_HEADS"])
    index = sum(row[:2] == ["pr", "view"] for row in previous)
    print(heads[min(index, len(heads) - 1)])
elif a[:2] == ["api", "user"]:
    print("me")
elif a[0] == "api" and "-F" in a:
    open(os.environ["FAKE_POSTED"], "w").write(open(a[a.index("-F") + 1].removeprefix("body=@")).read())
    print(json.dumps({"url": "https://github.com/o/r/pull/12#c1", "author": "me", "created": "t"}))
elif a[0] == "api":
    for row in json.loads(os.environ["FAKE_COMMENTS"]):
        print(json.dumps(row))
"""
POLICY_DRIVER = """import runpy
import sys
from pathlib import Path
from unittest.mock import patch

hook = Path(sys.argv[1])
sys.path.insert(0, str(hook.parent))
sys.path.insert(0, str(hook.parents[2]))
from scripts.lib import review_passes

original = review_passes.load_policy
def read_policy():
    if sys.argv[2] == "internal":
        raise RuntimeError("probe")
    return original(Path(sys.argv[2]))

with patch.object(review_passes, "load_policy", side_effect=read_policy):
    runpy.run_path(str(hook), run_name="__main__")
"""


def entry(name: str, verdict: str = "pass", digest: str = "") -> dict[str, object]:
    """A passes[] entry, hand-built so the wire format is checked independently of review_passes.py."""
    text = CLEAN if verdict == "pass" else CRITICAL
    real = hashlib.sha256(text.strip().encode()).hexdigest()
    return {"name": name, "verdict": verdict, "blocking": verdict == "fail", "summary_sha256": digest or real}


def artifact(*passes: dict[str, object]) -> dict[str, str]:
    """Env for the fake gh: the passes line plus the posted sections each pass was derived from."""
    parts = [CLEAN.strip()]  # the review-pr summary comes first
    for item in passes:
        if item["name"] != "review-pr":
            parts.append(f"<!-- coderails-review-pass {item['name']} -->")
            parts.append((CLEAN if item["verdict"] == "pass" else CRITICAL).strip())
    return {"FAKE_PASSES": json.dumps(list(passes)), "FAKE_TAIL": "\n".join(parts)}


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
    """A temp repo with origin/main and a feature commit; subclasses choose the file the PR touches."""

    touched = "hooks/x.py"
    eval_level = 1  # a hooks/ diff is outward: the derived minimum verification level

    def setUp(self) -> None:
        """Base commit on origin/main, then one feature commit touching `touched`."""
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
        self.eval_file = write_comment(self.tmp, self.sha, self.eval_level, frozen_sha=self.base)


class HookTests(Repo):
    """The Codex hook, run as Codex runs it, applies the required-reviewer policy."""

    def reason(self, policy: str = "", **env: str) -> str:
        """Permission-decision reason for `gh pr merge 7`, or empty when allowed."""
        environment = {**os.environ, "PATH": f"{shim(self.tmp, HOOK_SHIM)}{os.pathsep}{os.environ['PATH']}"}
        environment |= {
            "FAKE_SHA": self.sha,
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.tmp / "loops"),
            "CODERAILS_AGENTIC_LOOP_DIR": str(self.tmp / "loops"),
        }
        environment |= {"FAKE_EVAL_FILE": str(self.eval_file), **env}
        command = {"command": "gh pr merge 7"}
        payload = {"session_id": "s", "cwd": str(self.dir), "tool_name": "Bash", "tool_input": command}
        argv = [sys.executable, str(HOOK)]
        if policy:
            driver = self.tmp / "policy-driver.py"
            driver.write_text(POLICY_DRIVER)
            argv = [sys.executable, str(driver), str(HOOK), policy]
        result = subprocess.run(argv, input=json.dumps(payload), text=True, capture_output=True, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = cast(dict[str, dict[str, str]], json.loads(result.stdout)) if result.stdout.strip() else {}
        return output.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")

    def test_hooks_pr_with_only_review_pr_is_refused(self) -> None:
        """A v1 artifact (no passes line) on a hooks/ diff is denied, naming the missing pass and the remedy."""
        reason = self.reason()
        self.assertTrue(reason.startswith("required_review_missing:security-review"), reason)
        self.assertIn("post_review.py post", reason)
        self.assertNotIn("diff_manifest: off", reason)
        only_review_pr = artifact(entry("review-pr"))
        self.assertTrue(self.reason(**only_review_pr).startswith("required_review_missing:security-review"))

    def test_security_pass_present_proceeds(self) -> None:
        """Negative control: with the pass the same hook call allows, so the denial came from the policy."""
        self.assertEqual(self.reason(**artifact(entry("review-pr"), entry("security-review"))), "")

    def test_forged_pass_is_refused(self) -> None:
        """Negative control: a made-up hash, or a verdict the posted text does not support, is malformed."""
        forged = artifact(entry("review-pr"), entry("security-review", digest=ZERO))
        self.assertTrue(self.reason(**forged).startswith("review_passes_malformed"))
        lying = artifact(entry("review-pr"), entry("security-review", "fail"))
        lying["FAKE_PASSES"] = lying["FAKE_PASSES"].replace('"verdict": "fail"', '"verdict": "pass"')
        self.assertTrue(self.reason(**lying).startswith("review_passes_malformed"))

    def test_failed_pass_and_missing_artifact_are_refused(self) -> None:
        """A failed security pass, a missing artifact and a malformed passes line each deny."""
        failed = artifact(entry("review-pr"), entry("security-review", "fail"))
        self.assertTrue(self.reason(**failed).startswith("required_review_failed:security-review"))
        failed["FAKE_PASSES"] = failed["FAKE_PASSES"].replace('"blocking": true', '"blocking": false')
        self.assertTrue(self.reason(**failed).startswith("required_review_failed:security-review"))
        self.assertTrue(self.reason(FAKE_NO_ARTIFACT="1").startswith("review_artifact_missing"))
        self.assertTrue(self.reason(FAKE_PASSES='"nope"').startswith("review_passes_malformed"))

    def test_passes_line_for_another_head_is_ignored(self) -> None:
        """A passes line carrying a different head_sha does not satisfy the policy."""
        reason = self.reason(**artifact(entry("review-pr"), entry("security-review")), FAKE_PASSES_SHA="stale")
        self.assertTrue(reason.startswith("required_review_missing:security-review"), reason)

    def test_conflicting_summary_and_section_markers_are_refused(self) -> None:
        """The actual hook refuses ambiguous grammar even when every declared hash matches."""
        valid = artifact(entry("review-pr"), entry("security-review"))
        repeated = CRITICAL.replace("- injection", "None") + "\n" + CRITICAL
        for text in (CLEAN + CRITICAL, repeated, CLEAN + CLEAN):
            digest = hashlib.sha256(text.strip().encode()).hexdigest()
            given = artifact(entry("review-pr"), entry("security-review", digest=digest))
            given["FAKE_TAIL"] = CLEAN + "<!-- coderails-review-pass security-review -->\n" + text
            with self.subTest(text=text):
                self.assertTrue(self.reason(**given).startswith("review_passes_malformed"))
        duplicate = {
            **valid,
            "FAKE_TAIL": valid["FAKE_TAIL"] + "\n<!-- coderails-review-pass security-review -->\n" + CLEAN,
        }
        self.assertTrue(self.reason(**duplicate).startswith("review_passes_malformed"))
        self.assertEqual(self.reason(**valid), "")

    def test_policy_and_internal_refusals_do_not_prescribe_reposting(self) -> None:
        """Actual hook input/output keeps unreadable-policy and internal-error remedies distinct from reposting."""
        valid = artifact(entry("review-pr"), entry("security-review"))
        missing = self.tmp / "missing.json"
        malformed = self.tmp / "malformed.json"
        malformed.write_text("{")
        for policy, code in (
            (str(missing), "review_policy_unreadable"),
            (str(malformed), "review_policy_unreadable"),
            ("internal", "review_passes_check_error"),
        ):
            with self.subTest(policy=policy):
                reason = self.reason(policy=policy, **valid)
                self.assertTrue(reason.startswith(code), reason)
                self.assertNotIn("re-post", reason)
                self.assertNotIn("post_review.py post", reason)


class DocsOnlyTests(Repo):
    """A docs-only PR needs only review-pr."""

    touched = "docs/a.md"
    eval_level = 0

    def test_docs_only_needs_review_pr_only(self) -> None:
        """The bare v1 artifact is enough for docs."""
        environment = {**os.environ, "PATH": f"{shim(self.tmp, HOOK_SHIM)}{os.pathsep}{os.environ['PATH']}"}
        environment |= {"FAKE_SHA": self.sha, "CODERAILS_AGENTIC_LOOP_DIR": str(self.tmp / "loops")}
        environment["FAKE_EVAL_FILE"] = str(self.eval_file)
        command = {"command": "gh pr merge 7"}
        payload = {"session_id": "s", "cwd": str(self.dir), "tool_name": "Bash", "tool_input": command}
        result = subprocess.run(
            [sys.executable, str(HOOK)], input=json.dumps(payload), text=True, capture_output=True, env=environment
        )
        self.assertEqual((result.returncode, result.stdout.strip()), (0, ""))


class PostTests(Repo):
    """The Codex post_review.py: argument gate, derived passes line, no progress cache."""

    touched = "docs/a.md"

    def post(
        self,
        *arguments: str,
        provider: str = "codex",
        comments: list[dict[str, str]] | None = None,
        heads: list[str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
        """Run `post_review.py post ...` against a fake gh; returns (result, gh call log, posted body)."""
        log, posted = self.tmp / "gh.log", self.tmp / "posted.md"
        log.write_text("")
        env = {**os.environ, "PATH": f"{shim(self.tmp, POST_SHIM)}{os.pathsep}{os.environ['PATH']}"}
        env |= {
            "FAKE_SHA": self.sha,
            "FAKE_LOG": str(log),
            "FAKE_POSTED": str(posted),
            "FAKE_HEADS": json.dumps(heads or [self.sha]),
            "FAKE_COMMENTS": json.dumps(comments or []),
        }
        path = POST if provider == "codex" else ROOT / "scripts/post_review.py"
        result = subprocess.run(
            [sys.executable, str(path), "post", *arguments], cwd=self.dir, env=env, capture_output=True, text=True
        )
        return result, log, posted

    def test_posts_marker_then_passes_line(self) -> None:
        """First line is the v1 marker, second the passes line with derived verdicts."""
        clean, critical = self.tmp / "clean.md", self.tmp / "critical.md"
        clean.write_text(CLEAN)
        critical.write_text(CRITICAL)
        result, _, posted = self.post("12", "--summary", str(clean), "--pass", f"security-review={critical}")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = posted.read_text().splitlines()
        self.assertEqual(lines[0], f"<!-- coderails-review-summary v1 pr=12 head_sha={self.sha} -->")
        data = json.loads(lines[1].removeprefix("<!-- coderails-review-passes v1 ").removesuffix(" -->"))
        self.assertEqual(data["head_sha"], self.sha)
        verdicts = {p["name"]: (p["verdict"], p["blocking"]) for p in data["passes"]}
        self.assertEqual(verdicts, {"review-pr": ("pass", False), "security-review": ("fail", True)})

    def test_invalid_number_makes_no_gh_call(self) -> None:
        """Negative control: injection-shaped numbers fail with pr_number_invalid and the gh shim is never run."""
        clean = self.tmp / "clean.md"
        clean.write_text(CLEAN)
        for provider in ("claude", "codex"):
            for bad in ("7; id", "$(id)", "-1", "0", "07", "abc", ""):
                with self.subTest(provider=provider, bad=bad):
                    result, log, _ = self.post(bad, "--summary", str(clean), provider=provider)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("pr_number_invalid", result.stderr)
                    self.assertEqual(log.read_text(), "")

    def test_validate_operation_still_works(self) -> None:
        """The pre-existing validate operation keeps its interface."""
        clean = self.tmp / "clean.md"
        clean.write_text(CLEAN)
        done = subprocess.run([sys.executable, str(POST), "validate", str(clean)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("write_cache", POST.read_text())

    def test_both_provider_clis_select_and_validate_the_newest_authored_artifact(self) -> None:
        """The real CLI reuses only the newest valid same-author body, while foreign bodies stay excluded."""
        clean = self.tmp / "clean.md"
        clean.write_text(CLEAN)
        for provider in ("claude", "codex"):
            result, _, posted = self.post("12", "--summary", str(clean), provider=provider)
            self.assertEqual(result.returncode, 0, result.stderr)
            good = {"url": "old", "author": "me", "created": "t", "body": posted.read_text()}
            corrupt = {**good, "url": "corrupt", "body": "\n".join(good["body"].splitlines()[:2]) + "\n" + CRITICAL}
            for comments, reused in (
                ([good, corrupt], ""),
                ([corrupt], ""),
                ([good, {**good, "url": "new"}], "new"),
                ([good, {**corrupt, "author": "other"}], "old"),
            ):
                with self.subTest(provider=provider, reused=reused, count=len(comments)):
                    result, log, _ = self.post("12", "--summary", str(clean), provider=provider, comments=comments)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    calls = [json.loads(line) for line in log.read_text().splitlines()]
                    self.assertEqual(any("-F" in call for call in calls), not bool(reused))
                    if reused:
                        self.assertIn("Existing: " + reused, result.stdout)

    def test_both_provider_clis_keep_literal_paths_and_refuse_head_races(self) -> None:
        """Shell-looking paths are read literally; a changed head before or after posting cannot report success."""
        clean = self.tmp / "$(touch should-not-exist).md"
        clean.write_text(CLEAN)
        for provider in ("claude", "codex"):
            for heads, posts in (
                ([self.sha], True),
                ([self.sha, "b" * 40], False),
                ([self.sha, self.sha, "b" * 40], True),
            ):
                with self.subTest(provider=provider, heads=heads):
                    result, log, _ = self.post("12", "--summary", str(clean), provider=provider, heads=heads)
                    self.assertEqual(result.returncode, int(len(heads) > 1), result.stderr)
                    calls = [json.loads(line) for line in log.read_text().splitlines()]
                    self.assertEqual(any("-F" in call for call in calls), posts)
                    self.assertFalse((self.dir / "should-not-exist").exists())


class MirrorTests(unittest.TestCase):
    """Policy and library copies are byte-identical; the security reviewer exists on both providers."""

    def test_copies_are_byte_identical(self) -> None:
        """Mirrored files must not drift between the Claude root and the Codex package."""
        for name in (
            "policy/review_policy.json",
            "scripts/lib/review_passes.py",
            "scripts/lib/review_artifact.py",
            "scripts/lib/git_common.py",
            "scripts/lib/publication_gate.py",
            "capabilities/profiles.json",
        ):
            with self.subTest(name=name):
                self.assertEqual((ROOT / name).read_bytes(), (CODEX / name).read_bytes())

    def test_security_reviewer_on_both_providers(self) -> None:
        """Agent files exist, are read-only, are profiled and are in the Codex installer's name list."""
        claude = (ROOT / "agents/security-reviewer.md").read_text()
        self.assertRegex(claude, r"(?m)^name: security-reviewer$")
        self.assertRegex(claude, r"(?m)^disallowedTools: Write, Edit, NotebookEdit$")
        header = (CODEX / "agents/security-reviewer.toml").read_text().partition('developer_instructions = """')[0]
        self.assertRegex(header, r'(?m)^name = "security-reviewer"$')
        self.assertRegex(header, r'(?m)^sandbox_mode = "read-only"$')
        for root in (ROOT, CODEX):
            profiles = json.loads((root / "capabilities/profiles.json").read_text())
            self.assertEqual(profiles["agents"]["security-reviewer"], ["repo.inspect", "diff.read"])
        self.assertIn('"security-reviewer"', (ROOT / "scripts/installer/codex.py").read_text())


if __name__ == "__main__":
    unittest.main()
