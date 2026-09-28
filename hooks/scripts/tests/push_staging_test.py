"""Preserve tracked-only staging and literal repeated --add CLI behavior."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.workflow_push_fixture import PushFixture


class PushStagingTests(unittest.TestCase):
    """Every successful push lands only in a temporary local bare origin."""

    def test_tracked_untracked_and_deletion_matrix(self) -> None:
        """Commit only tracked changes and pre-staged files; warn for every foreign file."""
        for scenario in ("tracked", "untracked", "only-untracked", "multiple", "prestaged", "deleted"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                fixture = PushFixture(Path(directory))
                before = fixture.git(fixture.repo, "rev-parse", "HEAD")
                if scenario != "only-untracked":
                    (fixture.repo / "base.txt").write_text("modified")
                if scenario in ("untracked", "only-untracked", "multiple"):
                    (fixture.repo / "newfile.txt").write_text("foreign")
                if scenario == "multiple":
                    (fixture.repo / "another.txt").write_text("foreign")
                if scenario == "prestaged":
                    (fixture.repo / "prestaged.txt").write_text("owned")
                    fixture.git(fixture.repo, "add", "prestaged.txt")
                if scenario == "deleted":
                    (fixture.repo / "base.txt").unlink()
                result = fixture.push()
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0, output)
                after = fixture.git(fixture.repo, "rev-parse", "HEAD")
                if scenario == "only-untracked":
                    self.assertEqual(after, before)
                else:
                    self.assertNotEqual(after, before)
                    self.assertEqual(fixture.git(fixture.repo, "rev-parse", "origin/feature"), after)
                files = fixture.git(
                    fixture.repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
                ).splitlines()
                self.assertNotIn("newfile.txt", files)
                if scenario == "prestaged":
                    self.assertIn("prestaged.txt", files)
                if scenario == "deleted":
                    self.assertIn("base.txt", files)
                    self.assertNotIn("base.txt", fixture.git(fixture.repo, "ls-tree", "--name-only", "HEAD"))
                if scenario in ("untracked", "only-untracked", "multiple"):
                    self.assertIn("! Untracked", output)
                    self.assertIn("newfile.txt", output)
                    self.assertIn("git add", output)
                    if scenario == "multiple":
                        self.assertIn("another.txt", output)
                else:
                    self.assertNotIn("! Untracked", output)

    def test_explicit_paths_and_message_order(self) -> None:
        """Consume each --add argument literally without swallowing the commit message."""
        for arguments in (
            ("--add", "owned.txt"),
            ("--add", "owned.txt", "my message"),
            ("my message", "--add", "owned.txt"),
            ("--add", "owned.txt", "--add", "second.txt"),
        ):
            with self.subTest(arguments=arguments), tempfile.TemporaryDirectory() as directory:
                fixture = PushFixture(Path(directory))
                (fixture.repo / "base.txt").write_text("modified")
                for name in ("owned.txt", "second.txt", "foreign.txt"):
                    (fixture.repo / name).write_text(name)
                result = fixture.push(*arguments)
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0, output)
                files = fixture.git(
                    fixture.repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
                ).splitlines()
                self.assertIn("base.txt", files)
                self.assertIn("owned.txt", files)
                self.assertNotIn("foreign.txt", files)
                warnings = "\n".join(line for line in output.splitlines() if line.startswith("!"))
                self.assertIn("foreign.txt", warnings)
                self.assertNotIn("owned.txt", warnings)
                if "second.txt" in arguments:
                    self.assertIn("second.txt", files)
                if "my message" in arguments:
                    self.assertEqual(fixture.git(fixture.repo, "log", "-1", "--format=%s"), "my message")


if __name__ == "__main__":
    unittest.main()
