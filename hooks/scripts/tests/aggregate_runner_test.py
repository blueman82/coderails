"""Check aggregate discovery, skip accounting and Git isolation using inert suites."""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.run_all import isolated_environment, run_suites


class AggregateRunnerTests(unittest.TestCase):
    """Verify truthful suite accounting without invoking repository suites."""

    def test_empty_skip_and_mixed_results(self) -> None:
        """Require at least one executed success and no genuine failures."""
        with (
            tempfile.TemporaryDirectory() as temporary,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            directory = Path(temporary)
            self.assertEqual(run_suites(directory), 1)
            (directory / "skip_test.py").write_text("raise SystemExit(3)\n")
            self.assertEqual(run_suites(directory), 1)
            (directory / "pass_test.py").write_text("raise SystemExit(0)\n")
            self.assertEqual(run_suites(directory), 0)
            (directory / "failure_test.py").write_text("raise SystemExit(2)\n")
            self.assertEqual(run_suites(directory), 1)

    def test_skip_output_and_neighbouring_failure_codes(self) -> None:
        """Name skips honestly and never absorb exits immediately above or below three."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "skip_test.py").write_text("raise SystemExit(3)\n")
            (directory / "pass_test.py").write_text("raise SystemExit(0)\n")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(run_suites(directory), 0)
            self.assertIn("SKIPPED (prerequisite): skip_test.py", output.getvalue())
            self.assertIn("1 skipped", output.getvalue())
            (directory / "skip_test.py").unlink()
            for code in (1, 2, 4):
                (directory / "failure_test.py").write_text(f"raise SystemExit({code})\n")
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(run_suites(directory), 1)
                self.assertIn(f"FAILED (exit {code})", output.getvalue())
                self.assertNotIn("SKIPPED", output.getvalue())

    def test_unretired_suite_refuses_partial_coverage(self) -> None:
        """A Python-only runner cannot advertise success while old suites remain."""
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stderr(io.StringIO()):
            directory = Path(temporary)
            (directory / "pass_test.py").write_text("raise SystemExit(0)\n")
            (directory / "unretired.test.sh").write_text("exit 1\n")
            self.assertEqual(run_suites(directory), 1)

    def test_git_environment_removed(self) -> None:
        """Scrub every indexed override, preserving unrelated process settings."""
        with patch.dict(
            os.environ,
            {"GIT_DIR": "/wrong", "GIT_CONFIG_KEY_17": "bad", "GIT_CONFIG_VALUE_17": "bad", "KEEP_THIS": "yes"},
        ):
            environment = isolated_environment()
            self.assertNotIn("GIT_DIR", environment)
            self.assertNotIn("GIT_CONFIG_KEY_17", environment)
            self.assertNotIn("GIT_CONFIG_VALUE_17", environment)
            self.assertEqual(environment["KEEP_THIS"], "yes")


if __name__ == "__main__":
    unittest.main()
