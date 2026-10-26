#!/usr/bin/env python3
"""Negative controls for the receipt matcher: quoting, absolute paths, eval, ref movers, cd parsing, multi pushurl."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib import pr_workflow_match as match
from hooks.scripts.tests.receipt_test_support import git, make_repo
from scripts.lib import action_binding as ab


class MatchHardeningTests(unittest.TestCase):
    """A repo on a feature branch: only the explicit destination can make a push guarded."""

    def setUp(self) -> None:
        """Repo with origin, a feature branch checked out, and a directory whose name has a space."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.repo = str(make_repo(self.root / "r"))
        git(Path(self.repo), "switch", "-q", "-c", "feature")
        (self.root / "x y").mkdir()

    def names(self, command: str) -> list[str]:
        """Operation names guarded in `command`."""
        return [name for name, _, _ in match.guarded_segments(command, self.repo)]

    def test_implicit_push_destination_is_guarded_and_unbindable(self) -> None:
        """Git config can send a refspec-free push to main from a feature branch."""
        for key, value in (("push.default", "matching"), ("remote.origin.push", "refs/heads/main:refs/heads/main")):
            with self.subTest(config=key):
                git(Path(self.repo), "config", key, value)
                for command in ("git push", "git push origin"):
                    self.assertEqual(match.guarded_segments(command, self.repo), [])
                    found = match.guarded_segments(command, self.repo, implicit_push=True)
                    self.assertEqual([name for name, _, _ in found], ["git_push"])
                    self.assertIsNone(ab.binding("git_push", found[0][1], found[0][2]))
                git(Path(self.repo), "config", "--unset", key)
        self.assertEqual(self.names("git push origin feature"), [])

    def test_later_push_to_main_is_not_hidden_by_feature_push(self) -> None:
        """The legacy review gate checks a whole command, including pushes after a benign first push."""
        command = "git push origin feature && git push origin HEAD:main"
        self.assertTrue(match.targets_main(command, self.repo, "", "git_push"))
        self.assertEqual(self.names(command), ["git_push"])

    def test_env_split_string_push_is_guarded(self) -> None:
        """A supported env -S wrapper still exposes the literal push destination."""
        command = 'env -S "git push origin HEAD:main"'
        found = match.guarded_operations(command, self.repo, implicit_push=True)
        self.assertEqual([call.name for call in found], ["git_push"])

    def test_external_time_value_options_do_not_hide_push(self) -> None:
        """GNU time option values precede the executable."""
        self.assertEqual(self.names("/usr/bin/time -f %E -o report git push origin HEAD:main"), ["git_push"])

    def test_async_merge_request_is_guarded_but_result_lookup_is_not(self) -> None:
        """The stacked-PR PUT endpoint is a merge; polling its UUID is a read."""
        sha = "f" * 40
        request = f"gh api --method PUT repos/acme/widgets/pulls/7/merge-async -f sha={sha}"
        result = "gh api repos/acme/widgets/pulls/7/merge-async/11111111-1111-1111-1111-111111111111"
        self.assertEqual(self.names(request), ["merge"])
        self.assertEqual(self.names(result), [])

    def test_quoted_variable_and_glob_destinations_are_guarded(self) -> None:
        """Quoting, escaping and expansion must not hide a push to main; non-literal destinations are unbindable."""
        for command in (
            'git push origin "main"', 'git push origin HEAD:"main"', "git push origin 'HEAD:main'",
            'git push origin "HEAD:main"', r"git push origin HEAD:refs/heads/ma\in", "git push origin HEAD:$B",
            "git push origin HEAD:$(echo main)", "git push origin HEAD:ma*", "git push --mirror origin",
            "git push --all origin", "git push -o x origin +HEAD:main",
        ):  # fmt: skip
            with self.subTest(command=command):
                self.assertEqual(self.names(command), ["git_push"])
        for command in ("git push origin feature", 'git push origin HEAD:"feature"', "git push origin 'x:y'"):
            with self.subTest(command=command):
                self.assertEqual(self.names(command), [])
        for command in ("git push origin HEAD:$B", "git push origin HEAD:ma*"):
            _, segment, where = match.guarded_segments(command, self.repo)[0]
            self.assertIsNone(ab.binding("git_push", segment, where), command)

    def test_executable_paths_quotes_and_eval_do_not_hide_an_action(self) -> None:
        """Absolute or quoted git/gh, env wrapper by path, and eval of a string are matched."""
        pin = "--match-head-commit " + "a" * 40
        for command in (
            "/usr/bin/git push origin HEAD:main", '"/usr/bin/git" push origin HEAD:main',
            "'git' push origin HEAD:main", "/usr/bin/env git push origin HEAD:main",
            'eval "git push origin HEAD:main"', "eval 'git push origin HEAD:main'",
        ):  # fmt: skip
            with self.subTest(command=command):
                self.assertEqual(self.names(command), ["git_push"])
        for command in (f"/opt/homebrew/bin/gh pr merge 5 {pin}", f"'gh' pr merge 5 {pin}"):
            with self.subTest(command=command):
                self.assertEqual(self.names(command), ["merge"])
        self.assertEqual(self.names("/bin/bash /x/y/merge.py 5"), ["merge"])

    def test_headless_agent_prompt_guards_only_executable_text(self) -> None:
        """A headless child can run a merge, but option values and printed examples cannot."""
        for command in (
            'claude -p --dangerously-skip-permissions "gh pr merge 42"',
            'claude --print --permission-mode bypassPermissions "gh pr merge 42"',
            'codex exec --dangerously-bypass-approvals-and-sandbox "gh pr merge 42"',
            "bash -c 'codex exec \"gh pr merge 42\"'",
            'claude -p "gh pr merge 42 && echo done"',
            'echo ready && claude -p "gh pr merge 42 && echo done"',
        ):
            with self.subTest(command=command):
                self.assertEqual(self.names(command), ["merge"])
        for command in (
            "echo 'claude -p \"gh pr merge 42\"'",
            'claude -p --system-prompt "gh pr merge 42" "explain the code"',
            'codex exec --cd "gh pr merge 42" "explain the code"',
        ):
            with self.subTest(command=command):
                self.assertEqual(self.names(command), [])
        self.assertTrue(match.state_mutated_before_guard('git branch -f feature HEAD^ && claude -p "gh pr merge 42"'))

    def test_every_non_read_only_step_before_a_guard_is_refused(self) -> None:
        """Allowlist: unknown movers (push ., worktree -B, filter-branch, redirects into .git) taint the guard."""
        push = "git push origin feature:main"
        for before in (
            "git push . evil:feature", "git worktree add -B feature /tmp/w evil", "git filter-branch -f HEAD",
            "git update-index --add x", "echo x > .git/refs/heads/feature", "git gc", "git notes add -m x",
            "somescript.sh", "git branch -f feature evil", "git commit -m x", "echo $(git branch -f f e)",
            "git branch newbranch", "git remote add x y",
        ):  # fmt: skip
            with self.subTest(before=before):
                self.assertTrue(match.state_mutated_before_guard(f"{before} && {push}"))
        for before in (
            "git status", "git log --oneline | head -3", "cd /tmp", "echo hi", "git rev-parse HEAD", "pwd",
            "git branch --show-current", "git push origin feature", "git push origin feature:main",
        ):  # fmt: skip
            with self.subTest(before=before):
                self.assertFalse(match.state_mutated_before_guard(f"{before} && {push}"))

    def test_cd_is_parsed_like_a_shell(self) -> None:
        """Quoted/spaced cd moves the cwd; subshell, variable and missing targets never silently keep the old one."""
        target = str(self.root / "x y")
        found = match.guarded_segments(f'cd "{target}" && git push origin HEAD:main', self.repo)
        self.assertEqual([where for _, _, where in found], [target])
        found = match.guarded_segments("(cd /nonexistent-dir); git push origin HEAD:main", self.repo)
        self.assertEqual([where for _, _, where in found], [self.repo])  # a subshell cd does not persist
        for command in (
            "cd $SOMEWHERE && git push origin HEAD:main", "cd /nonexistent-dir && git push origin HEAD:main",
            "cd - && git push origin HEAD:main", "(cd /tmp && git push origin HEAD:main)",
            "cd /tmp && bash -c 'git push origin HEAD:main'",
        ):  # fmt: skip
            with self.subTest(command=command):
                found = match.guarded_segments(command, self.repo)
                self.assertEqual(len(found), 1)
                self.assertIsNone(ab.binding("git_push", found[0][1], found[0][2]))
        found = match.guarded_segments("cd /tmp | cat; git push origin HEAD:main", self.repo)  # pipeline: no move
        self.assertEqual([where for _, _, where in found], [self.repo])

    def test_background_cd_cannot_move_parent_shell_directory(self) -> None:
        """A background cd runs in a child; the guarded push remains in the original repo."""
        target = str(self.root / "x y")
        found = match.guarded_segments(f'cd "{target}" & git push origin HEAD:main', self.repo)
        self.assertEqual([where for _, _, where in found], [self.repo])


class MultiplePushUrlTests(unittest.TestCase):
    """A remote with several push urls pushes to all of them: the receipt can name only one, so it is unbindable."""

    def test_two_pushurls_are_unbindable_one_is_bound(self) -> None:
        """`remote set-url --add --push` twice: None; a single pushurl binds that repository."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp) / "r")
            git(repo, "remote", "set-url", "--push", "origin", "https://github.com/acme/widgets.git")
            self.assertIsNotNone(ab.binding("git_push", "git push origin HEAD:main", str(repo)))
            git(repo, "remote", "set-url", "--add", "--push", "origin", "https://github.com/evil/mirror.git")
            self.assertIsNone(ab.binding("git_push", "git push origin HEAD:main", str(repo)))


if __name__ == "__main__":
    unittest.main()
