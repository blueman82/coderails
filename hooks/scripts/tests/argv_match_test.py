"""Argv classifier: wrapper-proof git/script recognition that never matches quoted text."""

from __future__ import annotations

import re
import shlex
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib import argv_match, destructive_patterns, shell_context
from hooks.scripts.lib.pr_workflow_match import operations

# The regexes the gates used before the classifier, kept as literals to document the defect.
OLD_CLAUDE_COMMIT = re.compile(r"\bgit +commit\b")
OLD_CODEX_COMMIT = re.compile(r"(^|[\s;&|])git\s+commit(\s|$)")

COMMIT_FORMS = [
    "git commit -m x",
    "git -C /r commit -m x",
    "git -c user.name=x commit -m x",
    "/usr/bin/git commit -m x",
    "env A=1 git -C d commit",
    "bash -c 'git -C d commit -m x'",
    "sudo -u root git --no-pager commit",
    "cd d && git commit -m x",
    "true; git -p commit",
    "(git commit -m x)",
    "git --git-dir=.git commit",
    'git commit -m "unbalanced',
]
NOT_COMMIT = [
    'echo "git commit"',
    "echo 'git commit'",
    "git log --grep commit",
    "git status; echo done",
    'echo "a; git commit"',
    'echo "unbalanced git commit',
    "grep -n 'git commit' file",
]


def is_commit(command: str) -> bool:
    """Return whether any invocation in the command is a git commit."""
    return any(sub == "commit" for sub, _, _ in argv_match.git_calls(command))


class ClassifierTests(unittest.TestCase):
    """Commit recognition by subcommand, not by text."""

    def test_commit_forms_are_classified(self) -> None:
        """Every wrapper and global-option form resolves to subcommand commit."""
        for command in COMMIT_FORMS:
            with self.subTest(command=command):
                self.assertTrue(is_commit(command))

    def test_quoted_command_substitutions_are_executed(self) -> None:
        """Double quotes keep command substitutions live; single quotes do not."""
        for command in ('echo "$(git push origin HEAD:main)"', 'echo "`git push origin HEAD:main`"'):
            with self.subTest(command=command):
                self.assertEqual([call.name for call in operations(command)], ["git_push"])
        for command in ('echo "$(gh pr merge 519 --merge)"', 'echo "`gh pr merge 519 --merge`"'):
            with self.subTest(command=command):
                self.assertEqual([call.name for call in operations(command)], ["merge"])
        for command in ("echo '$(git push origin HEAD:main)'", r'echo "\$(git push origin HEAD:main)"'):
            self.assertEqual(operations(command), [])

    def test_quoted_and_other_subcommands_are_not_commit(self) -> None:
        """Quoted text, grep arguments and other subcommands never classify as commit."""
        for command in NOT_COMMIT:
            with self.subTest(command=command):
                self.assertFalse(is_commit(command))

    def test_old_regexes_missed_the_global_option_forms(self) -> None:
        """Negative control: the retired regexes do not see git -C / -c commit, the classifier does."""
        for command in ("git -C /r commit -m x", "git -c user.name=x commit -m x", "env A=1 git -C d commit"):
            with self.subTest(command=command):
                self.assertIsNone(OLD_CLAUDE_COMMIT.search(command))
                self.assertIsNone(OLD_CODEX_COMMIT.search(command))
                self.assertTrue(is_commit(command))

    def test_unbalanced_quote_falls_back_without_crashing(self) -> None:
        """A shlex failure uses the conservative whitespace fallback."""
        self.assertEqual(argv_match.git_calls('git commit -m "oops')[0][0], "commit")
        self.assertEqual(argv_match.git_calls("echo 'oops"), [])

    def test_git_invocation_decodes_options_and_clusters(self) -> None:
        """Global options are skipped, -C is returned, and short clusters decode."""
        sub, directory, rest = argv_match.git_invocation(
            ["git", "-C", "d", "-c", "a=b", "--no-pager", "commit", "-nm", "msg"]
        ) or ("", "", [])
        self.assertEqual((sub, directory), ("commit", "d"))
        self.assertEqual(argv_match.flags(rest, "mFCct"), {"-n", "-m"})
        self.assertEqual(argv_match.flags(["-m", "-n"], "m"), {"-m"})
        self.assertEqual(argv_match.flags(["--no-verify", "--message=x"]), {"--no-verify", "--message"})
        self.assertIsNone(argv_match.git_invocation(["echo", "git", "commit"]))

    def test_merge_option_values_do_not_become_noop_flags(self) -> None:
        """Required values consume the next token; optional signing values do not."""
        options = (
            "-m",
            "-F",
            "-s",
            "-X",
            "--message",
            "--file",
            "--into-name",
            "--strategy",
            "--strategy-option",
            "--cleanup",
        )
        for option in options:
            for value in ("--help", "--dry-run"):
                with self.subTest(option=option, value=value):
                    self.assertNotIn(value, argv_match.flags([option, value], "mFsX"))
        for rest in (["--help"], ["--dry-run"], ["-S", "--help"], ["-S", "--dry-run"]):
            with self.subTest(rest=rest):
                self.assertIn(rest[-1], argv_match.flags(rest, "mFsX"))

    def test_is_script_matches_by_basename_and_operation(self) -> None:
        """Interpreters, relative and absolute paths resolve; operations gate the match."""
        post = ("validate-structure", "post")
        for command in (
            "python3 scripts/post_evals.py post 5",
            "/usr/bin/env python3 /x/scripts/post_evals.py validate-structure e.json",
            "./scripts/post_evals.py post",
        ):
            with self.subTest(command=command):
                self.assertTrue(any(argv_match.is_script(a, "post_evals.py", post) for a in argv_match.argvs(command)))
        for command in ("python3 scripts/post_evals.py compute-result e.json", "cat scripts/post_evals.py post"):
            with self.subTest(command=command):
                self.assertFalse(any(argv_match.is_script(a, "post_evals.py", post) for a in argv_match.argvs(command)))
        wrapped = argv_match.argvs("bash -c 'python3 x/run_all.py'")
        self.assertTrue(any(argv_match.is_script(a, "run_all.py") for a in wrapped))


WRAPPED_COMMITS = [
    "command -p git commit -m x",
    "sudo -n git commit -m x",
    "time -p git commit -m x",
    "nice -n 5 git commit -m x",
    "exec -a name git commit -m x",
    "env -u HOME git commit -m x",
    "env -S 'git commit -m x'",
    "env --chdir d git commit -m x",
    "sudo --user root git commit -m x",
    "sudo --user=root git commit -m x",
    "timeout 60 git commit -m x",
    "timeout -s KILL 60 git commit -m x",
    "stdbuf -oL git commit -m x",
    "setsid git commit -m x",
    "xargs git commit -m x",
    "builtin git commit -m x",
    "{ git commit -m x; }",
    "if true; then git commit -m x; fi",
    "for i in 1; do git commit -m x; done",
    "! git commit -m x",
    "echo `git commit -m x`",
    ">/dev/null git commit -m x",
    "2>&1 git commit -m x",
    "> /dev/null git commit -m x",
    "bash -o pipefail -c 'git commit -m x'",
    "bash -O extglob -c 'git commit -m x'",
    "bash -c 'git commit -m x' # \"",
]
ABBREVIATED_NO_VERIFY = ["--no-verif", "--no-ver", "--no-v"]


class HardeningTests(unittest.TestCase):
    """Reviewer findings: wrapper options, shell keywords, redirections, comments and -c option values."""

    def test_shell_depth_marks_opaque_executable_bodies(self) -> None:
        """Bash, eval and quoted substitutions cannot disappear beyond five levels."""
        for inner in (
            "bash -c 'git push origin HEAD:main'",
            "eval 'git push origin HEAD:main'",
            'echo "$(git push origin HEAD:main)"',
        ):
            command = inner
            for _ in range(5):
                command = "bash -c " + shlex.quote(command)
            with self.subTest(inner=inner):
                self.assertTrue(shell_context.opaque_execution(command))
        command = "git push origin HEAD:main"
        for _ in range(5):
            command = "bash -c " + shlex.quote(command)
        self.assertFalse(shell_context.opaque_execution(command))

    def test_directories_are_invocation_local(self) -> None:
        """Git -C composes while wrapper, nested shell and subshell directories stay local."""
        commands = {
            "git -C a -C ../b status; git status": ["/base/b", "/base"],
            "env --chdir a git status; git status": ["/base/a", "/base"],
            "bash -c 'cd a && git status'; git status": ["/base/a", "/base"],
            "(cd a && git status); git status": ["/base/a", "/base"],
            "cd 'a space' && git status": ["/base/a space"],
        }
        for command, expected in commands.items():
            with self.subTest(command=command):
                self.assertEqual([cwd for _, cwd, _ in argv_match.git_calls(command, "/base")], expected)
        source = "env A=1 git -C 'a space' status"
        self.assertEqual(shell_context.invocations(source, "/base")[-1][0], source)
        for command in ("git -C", "env --chdir", "sudo -u", "bash -o pipefail -c"):
            with self.subTest(command=command):
                self.assertEqual(argv_match.git_calls(command, "/base"), [])

    def test_wrapped_and_grouped_commits_are_seen(self) -> None:
        """Each form resolves to a commit; the retired regex missed most of them."""
        for command in WRAPPED_COMMITS:
            with self.subTest(command=command):
                self.assertTrue(is_commit(command))

    def test_wrapper_flags_do_not_swallow_the_command(self) -> None:
        """Negative control: -p and -n are flags for command, time and sudo, so git stays argv[0]."""
        for command in ("command -p git commit", "time -p git commit", "sudo -n git commit"):
            with self.subTest(command=command):
                self.assertEqual(argv_match.argvs(command)[-1][0], "git")

    def test_quoted_and_inert_forms_still_do_not_match(self) -> None:
        """Keywords, redirections and wrappers do not make text or other commands count."""
        for command in (
            "if true; then echo 'git commit'; fi",
            "timeout 5 echo git commit",
            "echo > git commit",
            "{ git status; }",
            "bash -c 'echo hi' # \"",
        ):
            with self.subTest(command=command):
                self.assertFalse(is_commit(command))

    def test_abbreviated_no_verify_is_recognised_by_the_destructive_gate(self) -> None:
        """Git accepts any unambiguous prefix; only the shared check sees them (exact flags() stays exact)."""
        for flag in ABBREVIATED_NO_VERIFY:
            with self.subTest(flag=flag):
                self.assertEqual(
                    destructive_patterns.permanent_pattern(f"git commit {flag} -m x", "")[1], "git-commit-no-verify"
                )
        self.assertEqual(destructive_patterns.permanent_pattern("git commit --no-edit -m x", ""), ("", ""))

    def test_is_script_skips_interpreter_options_and_leading_progress(self) -> None:
        """The post ceremony and the full suite are counted behind -W/-X/-m and a leading --progress option."""
        post = ("validate-structure", "post")
        for command in (
            "python3 scripts/post_evals.py --progress p post path",
            "python3 -W error scripts/post_evals.py post 5",
        ):
            with self.subTest(command=command):
                self.assertTrue(any(argv_match.is_script(a, "post_evals.py", post) for a in argv_match.argvs(command)))
        for command in (
            "python3 -W error run_all.py",
            "python3 -X dev run_all.py",
            "timeout 900 python3 run_all.py",
            "env --chdir d python3 run_all.py",
            "uv run python run_all.py",
            "python3 -m hooks.scripts.tests.run_all",
        ):
            with self.subTest(command=command):
                self.assertTrue(any(argv_match.is_script(a, "run_all.py") for a in argv_match.argvs(command)))
        self.assertFalse(
            any(argv_match.is_script(a, "run_all.py") for a in argv_match.argvs("python3 -c 'x' run_all.py"))
        )

    def test_script_operation_is_not_an_argument_or_option_value(self) -> None:
        """Only the operation counts; a path or --progress value may be named post."""
        for command in (
            "python3 scripts/post_evals.py validate-embed evals.json post",
            "python3 scripts/post_evals.py compute-result post",
            "python3 scripts/post_evals.py --progress post compute-result evals.json",
        ):
            with self.subTest(command=command):
                self.assertFalse(
                    any(argv_match.is_script(a, "post_evals.py", "post") for a in argv_match.argvs(command))
                )
        for command in (
            "python3 scripts/post_evals.py --progress=p post 5 evals.json",
            "python3 scripts/post_evals.py --prog p post 5 evals.json",
            "python3 scripts/post_evals.py -- post 5 evals.json",
            "python3 scripts/post_evals.py --progress p -- post 5 evals.json",
        ):
            with self.subTest(command=command):
                self.assertTrue(
                    any(argv_match.is_script(a, "post_evals.py", "post") for a in argv_match.argvs(command))
                )


if __name__ == "__main__":
    unittest.main()
