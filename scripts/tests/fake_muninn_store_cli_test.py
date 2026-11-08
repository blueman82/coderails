"""Check that the fake Muninn CLI refuses value flags with no value."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.tests.fake_muninn_case import StoreCase  # noqa: E402


class MissingAddValues(StoreCase):
    """Check every value-taking add flag at the CLI boundary."""

    def test_value_flags_need_values(self) -> None:
        """Return one JSON refusal for a flag with no value."""
        for flag in (
            "--kind",
            "--text",
            "--supersedes",
            "--confidence",
            "--valid-until",
            "--sensitivity",
            "--contradicts",
            "--scope-loop",
            "--cite",
            "--quote",
            "--tag",
        ):
            with self.subTest(flag=flag):
                self.assertEqual(self.muninn("know", "add", flag), (2, {"error": "bad_usage"}))


class MappedRequestScope(StoreCase):
    """The public fake must use the mapped repository identity across linked checkouts."""

    def test_linked_worktree_and_primary_share_notes_but_plain_directory_does_not(self) -> None:
        """A worktree path must not make the fake return a foreign project scope."""
        primary, linked, plain = (self.tmp / name for name in ("primary", "linked", "plain"))
        plain.mkdir()
        commands = [
            ["git", "init", "-q", str(primary)],
            [
                "git",
                "-C",
                str(primary),
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@test",
                "commit",
                "--allow-empty",
                "-qm",
                "base",
            ],
            ["git", "-C", str(primary), "worktree", "add", "-q", "-b", "linked", str(linked)],
        ]
        for command in commands:
            subprocess.run(command, capture_output=True, text=True, check=True)
        previous = Path.cwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(linked)
        code, request = self.muninn("learn", "request", "--session", "s1", "--task", "L1")
        self.assertEqual(code, 0, request)
        self.assertEqual(request["scope"], {"project_id": str(primary.resolve()), "task": "L1"})
        self.assertEqual(
            self.muninn("learn", "complete", request["id"], "--kind", "lesson", "--content", "Mapped lesson")[0], 0
        )
        code, linked_rows = self.muninn("know", "list", "--task", "L1")
        self.assertEqual(code, 0)
        self.assertEqual(len(linked_rows["knowledge"]), 1)
        os.chdir(primary)
        self.assertEqual(self.muninn("know", "list", "--task", "L1"), (0, linked_rows))
        os.chdir(plain)
        self.assertEqual(self.muninn("know", "list", "--task", "L1"), (0, {"knowledge": []}))
        code, request = self.muninn("learn", "request", "--session", "s1", "--task", "L1")
        self.assertEqual((code, request["scope"]["project_id"]), (0, str(plain.resolve())))


if __name__ == "__main__":
    unittest.main()
