"""Argv classifier: wrapper-proof git/script recognition that never matches quoted text."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib import argv_match

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


if __name__ == "__main__":
    unittest.main()
