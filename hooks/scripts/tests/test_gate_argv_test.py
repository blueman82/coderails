"""The Claude test gate keys on the git subcommand, so global options and wrappers cannot dodge it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

HOOK = Path(__file__).resolve().parent.parent / "test_gate.py"

DENIED = [
    "git -C /r commit -m x",
    "git -c user.name=x commit -m x",
    "/usr/bin/git commit -m x",
    "env A=1 git -C d commit",
    "bash -c 'git -C d commit -m x'",
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


if __name__ == "__main__":
    unittest.main()
