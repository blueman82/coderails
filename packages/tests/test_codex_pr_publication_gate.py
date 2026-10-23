"""Codex direct-merge arm: pr_publication_gate denies gh pr merge and merge.py on a publication violation."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast

# Not importing scripts.tests.*: that would bind the root `scripts` package and break the Codex tests that need
# packages/codex/scripts under the same name.
ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "packages/codex/hooks/scripts/pr_publication_gate.py"
SECRET = ".en" + "v"  # two parts so no source line spells the secret-file name
GH_SHIM = """#!/bin/sh
case "$1 $2" in
  "pr view")
    case "$5" in
      headRefOid) if [ "$3" = 1 ]; then echo "$CLEAN_SHA"; else echo "$FAKE_SHA"; fi ;;
      baseRefOid) echo "$BASE_SHA" ;;
      number) case "$3" in https://github.com/o/r/pull/*) echo "${3##*/}" ;; feat-b) echo 7 ;; esac ;;
    esac ;;
esac
exit 0
"""


def git_cmd(cwd: Path, *args: str) -> str:
    """Run Git in a temp repo with a fixed identity."""
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t"}
    env |= {"GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


def install_gh_shim(directory: Path) -> Path:
    """Write an executable fake gh into directory/bin and return that bin directory."""
    bin_dir = directory / "bin"
    bin_dir.mkdir(exist_ok=True)
    shim = bin_dir / "gh"
    shim.write_text(GH_SHIM)
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    return bin_dir


class CodexPublicationGateTests(unittest.TestCase):
    """Run the hook as Codex does: JSON payload on stdin, fake gh on PATH, a real temp repo."""

    def setUp(self) -> None:
        """Build origin/main with one script and one doc, then commit a secret-shaped file on a feature branch."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.dir = Path(temporary.name) / "repo"
        self.dir.mkdir()
        self.loop = Path(temporary.name) / "loops"
        git_cmd(self.dir, "init", "-q", "-b", "main")
        (self.dir / "README.md").write_text("doc\n")
        git_cmd(self.dir, "add", "-A")
        git_cmd(self.dir, "commit", "-qm", "base")
        git_cmd(self.dir, "update-ref", "refs/remotes/origin/main", "HEAD")
        git_cmd(self.dir, "checkout", "-qb", "feature/x")
        git_cmd(self.dir, "remote", "add", "origin", "https://github.com/o/r.git")
        git_cmd(self.dir, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        (self.dir / SECRET).write_text("k=v\n")
        git_cmd(self.dir, "add", "-A")
        git_cmd(self.dir, "commit", "-qm", "secret")
        self.sha = git_cmd(self.dir, "rev-parse", "HEAD").strip()
        self.env = {
            **os.environ,
            "PATH": f"{install_gh_shim(self.dir.parent)}{os.pathsep}{os.environ['PATH']}",
            "FAKE_SHA": self.sha,
            "CLEAN_SHA": git_cmd(self.dir, "rev-parse", "origin/main").strip(),
            "BASE_SHA": git_cmd(self.dir, "rev-parse", "origin/main").strip(),
            "CODERAILS_AGENTIC_LOOP_DIR": str(self.loop),
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.loop),
        }

    def hook(self, command: str) -> dict[str, object]:
        """Run the hook for one Bash command and return its JSON output ({} when it allows)."""
        payload = {"session_id": "s1", "cwd": str(self.dir), "tool_name": "Bash", "tool_input": {"command": command}}
        result = subprocess.run(
            [sys.executable, str(HOOK)], input=json.dumps(payload), text=True, capture_output=True, env=self.env
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def reason(self, command: str) -> str:
        """Return the permission-decision reason, or empty when the hook allowed."""
        output = cast(dict[str, str], self.hook(command).get("hookSpecificOutput") or {})
        return output.get("permissionDecisionReason", "")

    def config(self, text: str) -> None:
        """Write the repo's workflow config."""
        (self.dir / ".coderails").mkdir(exist_ok=True)
        (self.dir / ".coderails/workflow.config.yaml").write_text(text)

    def test_denies_every_merge_form(self) -> None:
        """Plain, bash -c wrapped and merge.py invocations are denied with the reason code first."""
        for command in (
            "gh pr merge 7 --merge",
            "bash -c 'gh pr merge 7'",
            "python3 scripts/merge.py 7",
            "gh api -X PUT repos/o/r/pulls/7/merge",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.reason(command).startswith("diff_manifest:denied_path"), command)

    def test_non_merge_commands_pass(self) -> None:
        """Negative control: ordinary commands are not touched."""
        self.assertEqual(self.reason("git status"), "")
        self.assertEqual(self.reason("gh pr view 7"), "")

    def test_body_flag_values_remain_guarded(self) -> None:
        """Quoted and equals-form body values cannot turn a protected diff into a no-op."""
        for value in ("--help", "--dry-run"):
            for option in (f"--body '{value}'", f"--body={value}", f"--subject '{value}'"):
                command = f"gh pr merge 7 {option} --merge"
                with self.subTest(command=command):
                    self.assertTrue(self.reason(command).startswith("diff_manifest:denied_path"), command)
            self.assertEqual(self.reason(f"gh pr merge 7 {value}"), "")

    def test_lifecycle_body_values_remain_guarded(self) -> None:
        """Only actual Git lifecycle options are harmless, not the same text in a body."""
        for flag in ("--abort", "--continue", "--quit", "--skip"):
            with self.subTest(flag=flag):
                self.assertTrue(
                    self.reason(f"gh pr merge 7 --body 'git merge {flag}' --merge").startswith(
                        "diff_manifest:denied_path"
                    )
                )
                self.assertEqual(self.reason(f"git merge {flag}"), "")

    def test_off_passes(self) -> None:
        """Negative control: diff_manifest off lets the same merge through."""
        self.config("diff_manifest: off\n")
        self.assertEqual(self.reason("gh pr merge 7"), "")

    def test_clean_diff_passes(self) -> None:
        """Negative control: a clean docs-only PR is not blocked by the default."""
        git_cmd(self.dir, "reset", "-q", "--hard", "origin/main")
        (self.dir / "docs.md").write_text("x\n")
        git_cmd(self.dir, "add", "-A")
        git_cmd(self.dir, "commit", "-qm", "docs")
        self.env["FAKE_SHA"] = git_cmd(self.dir, "rev-parse", "HEAD").strip()
        self.assertEqual(self.reason("gh pr merge 7"), "")

    def test_owned_graph_unit_needs_manifest_binding(self) -> None:
        """The direct hook uses its session ID to refuse an unbound graph publication."""
        common = git_cmd(self.dir, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        progress = self.loop / common.replace("/", "-") / "s1" / "progress.json"
        progress.parent.mkdir(parents=True)
        progress.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "session_id": "s1",
                    "loop_id": "test-loop",
                    "work_units": {"C1": {"worktree": str(self.dir), "manifest": ["docs/**"]}},
                }
            )
        )
        self.env["CLAUDE_AGENTIC_LOOP_DIR"] = str(self.loop / "other-root")
        self.assertTrue(self.reason("gh pr merge 1").startswith("diff_manifest:manifest_unreadable"))
        self.env["CLAUDE_AGENTIC_LOOP_DIR"] = str(self.loop)
        self.env["CODERAILS_AGENTIC_LOOP_DIR"] = str(self.loop / "other-root")
        self.assertEqual(self.reason("gh pr merge 1"), "")

    def test_gh_repo_retarget_refuses_even_clean_diff(self) -> None:
        """A same-number PR in another repository cannot borrow this repository's clean result."""
        git_cmd(self.dir, "reset", "-q", "--hard", "origin/main")
        (self.dir / "docs.md").write_text("x\n")
        git_cmd(self.dir, "add", "-A")
        git_cmd(self.dir, "commit", "-qm", "docs")
        self.env["FAKE_SHA"] = git_cmd(self.dir, "rev-parse", "HEAD").strip()
        self.assertEqual(self.reason("gh pr merge 7"), "")
        self.assertTrue(self.reason("GH_REPO=other/repo gh pr merge 7").startswith("pr_repo_override:"))
        self.env["GH_REPO"] = "other/repo"
        self.assertTrue(self.reason("gh pr merge 7").startswith("pr_repo_override:"))

    def test_base_edit_then_merge_is_refused_before_stale_base_check(self) -> None:
        """A shell line cannot change the PR base after the PreToolUse check and then merge it."""
        git_cmd(self.dir, "reset", "-q", "--hard", "origin/main")
        (self.dir / "docs.md").write_text("x\n")
        git_cmd(self.dir, "add", "-A")
        git_cmd(self.dir, "commit", "-qm", "docs")
        self.env["FAKE_SHA"] = git_cmd(self.dir, "rev-parse", "HEAD").strip()
        self.assertEqual(self.reason("gh pr merge 7"), "")
        command = "gh pr edit 7 --base old-release && gh pr merge 7"
        self.assertTrue(self.reason(command).startswith("pr_base_mutation:"))
        command = "gh api -X PATCH repos/o/r/pulls/7 -f base=old-release && gh pr merge 7"
        self.assertTrue(self.reason(command).startswith("pr_base_mutation:"))
        command = "gh api -X PATCH repos/o/r/pulls/7 --input /tmp/base-change.json && gh pr merge 7"
        self.assertTrue(self.reason(command).startswith("pr_base_mutation:"))
        command = 'gh api "repos/o/r/pulls/7" -X PATCH --input /tmp/base-change.json && gh pr merge 7'
        self.assertTrue(self.reason(command).startswith("pr_base_mutation:"))

    def test_unreadable_policy_fails_closed(self) -> None:
        """A policy file that cannot be read denies with manifest_unreadable."""
        self.config(f"diff_manifest_policy: {self.dir}/missing.json\n")
        self.assertTrue(self.reason("gh pr merge 7").startswith("diff_manifest:manifest_unreadable"))

    def test_the_merged_pr_is_the_one_checked(self) -> None:
        """PR 7 is violating and PR 1 is clean: a flag value, a URL or a branch name never swaps the target."""
        for command in (
            "gh pr merge --body 1 7",
            "gh pr merge --body=1 7 --squash",
            "gh pr merge https://github.com/o/r/pull/7",
            "gh pr merge feat-b",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.reason(command).startswith("diff_manifest:denied_path"), command)
        self.assertEqual(self.reason("gh pr merge 1"), "")  # control: the clean PR itself is allowed

    def test_unresolvable_target_denies(self) -> None:
        """-R/--repo, another repo's URL and an unknown branch deny instead of using the current branch's PR."""
        for command in (
            "gh pr merge --repo other/repo 1",
            "gh pr merge https://github.com/x/y/pull/1",
            "gh pr merge no-such-branch",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.reason(command).startswith("pr_number_invalid"), command)

    def test_unit_flags_are_enforced_on_the_merge_script(self) -> None:
        """merge.py --unit 2 --progress P 7 gates PR 7 (not PR 2) against unit 2's manifest."""
        git_cmd(self.dir, "reset", "-q", "--hard", "origin/main")
        (self.dir / "docs.md").write_text("x\n")
        git_cmd(self.dir, "add", "-A")
        git_cmd(self.dir, "commit", "-qm", "docs")
        self.env["FAKE_SHA"] = git_cmd(self.dir, "rev-parse", "HEAD").strip()
        progress = self.dir.parent / "progress.json"
        progress.write_text(
            json.dumps(
                {
                    "session_id": "s",
                    "loop_id": "l",
                    "work_units": {"2": {"manifest": ["src/**"], "worktree": str(self.dir)}},
                }
            )
        )
        flags = f"--unit 2 --progress {progress}"
        self.assertTrue(self.reason(f"python3 scripts/merge.py {flags} 7").startswith("diff_manifest:out_of_manifest"))
        self.assertEqual(self.reason("python3 scripts/merge.py 7"), "")  # control: no unit, clean docs diff passes

    def test_unresolvable_head_fails_closed(self) -> None:
        """No head SHA from gh means the diff cannot be read: deny, not allow."""
        self.env["FAKE_SHA"] = ""
        self.assertTrue(self.reason("gh pr merge 7").startswith("diff_manifest:manifest_unreadable"))

    def test_outer_cd_before_shell_wrapper_binds_the_intended_worktree(self) -> None:
        """A nested merge uses its preceding cd; the same unit from the starting cwd is refused."""
        git_cmd(self.dir, "reset", "-q", "--hard", "origin/main")
        (self.dir / "docs.md").write_text("canary\n")
        git_cmd(self.dir, "add", "-A")
        git_cmd(self.dir, "commit", "-qm", "docs")
        self.env["FAKE_SHA"] = git_cmd(self.dir, "rev-parse", "HEAD").strip()
        other = self.dir.parent / "other-worktree"
        git_cmd(self.dir, "worktree", "add", "-qb", "feature/intended", str(other), "HEAD")
        progress = self.dir.parent / "progress.json"
        progress.write_text(
            json.dumps(
                {"session_id": "s", "loop_id": "l", "work_units": {"2": {"manifest": ["*.md"], "worktree": str(other)}}}
            )
        )
        command = f"python3 scripts/merge.py 7 --unit 2 --progress {progress}"
        self.assertTrue(self.reason(command).startswith("diff_manifest:manifest_unreadable"))
        self.assertEqual(self.reason(f"cd {other} && {command}"), "")
        self.assertEqual(self.reason(f"cd {other} && bash -c '{command}'"), "")

    def test_subshell_and_brace_groups_bind_the_trailing_unit_to_their_actual_cwd(self) -> None:
        """A subshell restores the starting worktree; a brace group retains its cd."""
        git_cmd(self.dir, "reset", "-q", "--hard", "origin/main")
        (self.dir / "docs.md").write_text("canary\n")
        git_cmd(self.dir, "add", "-A")
        git_cmd(self.dir, "commit", "-qm", "docs")
        self.env["FAKE_SHA"] = git_cmd(self.dir, "rev-parse", "HEAD").strip()
        other = self.dir.parent / "other-worktree"
        git_cmd(self.dir, "worktree", "add", "-qb", "feature/intended", str(other), "HEAD")
        paths = [self.dir.parent / "own-progress.json", self.dir.parent / "other-progress.json"]
        for path, worktree in zip(paths, (self.dir, other)):
            path.write_text(
                json.dumps(
                    {
                        "session_id": "s",
                        "loop_id": "l",
                        "work_units": {"2": {"manifest": ["*.md"], "worktree": str(worktree)}},
                    }
                )
            )
        own, intended = (f"python3 scripts/merge.py 7 --unit 2 --progress {path}" for path in paths)
        for command, denied in (
            (f"(cd {other} && {intended}); {own}", False),
            (f"(cd {other} && {intended}); {intended}", True),
            (f"{{ cd {other} && {intended}; }}; {intended}", False),
        ):
            with self.subTest(command=command):
                reason = self.reason(command)
                self.assertEqual(bool(reason), denied, reason)
                if denied:
                    self.assertTrue(reason.startswith("diff_manifest:manifest_unreadable"), reason)


class RegistrationTests(unittest.TestCase):
    """The hook is shipped, executable and registered under the Bash matcher."""

    def test_registered_and_executable(self) -> None:
        """hooks.json lists the hook under ^Bash$ and the file is executable."""
        data = json.loads((ROOT / "packages/codex/hooks/hooks.json").read_text())["hooks"]["PreToolUse"]
        commands = [h["command"] for group in data if group["matcher"] == "^Bash$" for h in group["hooks"]]
        self.assertIn('"${PLUGIN_ROOT}/hooks/scripts/pr_publication_gate.py"', commands)
        self.assertTrue(os.access(HOOK, os.X_OK))

    def test_entrypoint_mode_fixture(self) -> None:
        """python_entrypoint_modes records the new hook as executable."""
        modes = json.loads((ROOT / "hooks/scripts/tests/fixtures/python_entrypoint_modes.json").read_text())
        self.assertEqual(modes.get("packages/codex/hooks/scripts/pr_publication_gate.py"), "100755")
        self.assertEqual(modes.get("scripts/lib/publication_gate.py"), "100644")
        self.assertEqual(modes.get("packages/codex/scripts/lib/publication_gate.py"), "100644")


if __name__ == "__main__":
    unittest.main()
