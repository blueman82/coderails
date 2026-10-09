"""The Claude test gate keys on the git subcommand, so global options and wrappers cannot dodge it."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

HOOK = Path(__file__).resolve().parent.parent / "test_gate.py"

DENIED = [
    "git -C . commit -m x",
    "git -c user.name=x commit -m x",
    "/usr/bin/git commit -m x",
    "env A=1 git -C . commit",
    "bash -c 'git -C . commit -m x'",
    "git commit -nm x",
    'git commit -m "unbalanced',
]
ALLOWED = ['echo "git commit"', "git log --grep commit", "git status", 'echo "unbalanced git commit', "git push x"]


class TestGateArgvTests(unittest.TestCase):
    """With a failing project test command every commit form denies and no other command does."""

    def setUp(self) -> None:
        """Create a project whose opt-in test command always fails."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        (self.project / ".claude").mkdir()
        (self.project / ".claude/test_command").write_text("false\n", encoding="utf-8")

    def decision(self, command: str) -> bool:
        """Return whether the hook denied the command (and exited cleanly)."""
        done = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
            capture_output=True,
            text=True,
            cwd=self.project,
            env=os.environ | {"CODERAILS_TEST_OUTPUT_DIR": str(self.project / "logs")},
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        output: dict[str, Any] = json.loads(done.stdout)["hookSpecificOutput"] if done.stdout.strip() else {}
        return bool(output.get("permissionDecision") == "deny")

    def test_commit_forms_deny_and_other_commands_do_not(self) -> None:
        """Acceptance 1, 2 and the shlex-failure control on the Claude gate."""
        for command in DENIED:
            with self.subTest(command=command):
                self.assertTrue(self.decision(command))
        for command in ALLOWED:
            with self.subTest(command=command):
                self.assertFalse(self.decision(command))

    def test_effective_project_controls_the_test_command(self) -> None:
        """Commit tests belong to the directory selected by Git or the supported shell prefix."""
        target = self.project / "target space"
        (target / ".claude").mkdir(parents=True)
        (target / ".claude/test_command").write_text("false\n", encoding="utf-8")
        (self.project / ".claude/test_command").write_text("true\n", encoding="utf-8")
        quoted = shlex.quote(str(target))
        for command in (
            f"git -C {quoted} commit -m x",
            f"cd {quoted} && git commit -m x",
            f"env --chdir {quoted} git commit -m x",
            f"bash -c {shlex.quote(f'cd {quoted} && git commit -m x')}",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.decision(command))

    def test_unconfigured_target_does_not_run_the_origin_tests(self) -> None:
        """The opt-in contract applies to the committing project rather than an unrelated process cwd."""
        target = self.project / "unconfigured"
        target.mkdir()
        self.assertFalse(self.decision(f"git -C {shlex.quote(str(target))} commit -m x"))

    def test_explicit_git_selection_controls_config(self) -> None:
        """The original global prefix selects metadata and worktree even when process cwd differs."""
        target = self.project / "selected space"
        subprocess.run(["git", "init", "-q", str(target)], check=True)
        (target / ".claude").mkdir()
        config = target / ".claude/test_command"
        config.write_text("false\n", encoding="utf-8")
        (self.project / ".claude/test_command").write_text("true\n", encoding="utf-8")
        commands = (
            f"git --git-dir {shlex.quote(str(target / '.git'))} --work-tree {shlex.quote(str(target))} commit",
            f"git --git-dir={shlex.quote(str(target / '.git'))} --work-tree={shlex.quote(str(target))} commit",
            "git -C 'selected space' -C . commit",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(self.decision(command))
        config.write_text("true\n", encoding="utf-8")
        (self.project / ".claude/test_command").write_text("false\n", encoding="utf-8")
        for command in commands:
            with self.subTest(command=command, control="unrelated failure"):
                self.assertFalse(self.decision(command))


if __name__ == "__main__":
    unittest.main()
