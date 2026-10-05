"""Keep source-quality feedback advisory and empty input silent."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.native_hook_test_support import HookCase

ROOT = Path(__file__).resolve().parents[3]


class QualityFeedbackTests(HookCase):
    """Inspect one actual source defect through the native feedback hook."""

    def test_advisory_whitespace(self) -> None:
        """A trailing-space finding nudges without denying or failing the hook."""
        self.assertEqual(self.output("quality_feedback", {}), {})
        bad = self.directory / "bad.py"
        bad.write_text("x \n", encoding="utf-8")
        result = self.invoke("quality_feedback", {"tool_input": {"file_path": str(bad)}})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("warn-only", result.stdout)
        self.assertIn("trailing whitespace", result.stdout)
        self.assertNotIn('"permissionDecision": "deny"', result.stdout)

    def test_filename_containing_the_clean_summary_does_not_suppress_feedback(self) -> None:
        """A path spelling `0 finding(s)` plus a real finding still gives feedback; the old substring check hid it."""
        bad = self.directory / "a 0 finding(s).py"
        bad.write_text("x = 1 \n", encoding="utf-8")
        plain = subprocess.run(
            [sys.executable, str(ROOT / "scripts/quality/check.py"), "--root", str(ROOT), "--paths", str(bad)],
            capture_output=True,
            text=True,
            check=False,
        )
        # negative control: the pre-change test (`"0 finding(s)" not in text`) would have stayed silent here
        self.assertIn("0 finding(s)", plain.stdout + plain.stderr)
        self.assertIn("1 finding(s)", plain.stdout)
        result = self.invoke("quality_feedback", {"tool_input": {"file_path": str(bad)}})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("trailing whitespace", result.stdout)

    def test_clean_file_stays_silent(self) -> None:
        """A file with no findings produces no feedback."""
        good = self.directory / "good.py"
        good.write_text('"""Fixture."""\n', encoding="utf-8")
        result = self.invoke("quality_feedback", {"tool_input": {"file_path": str(good)}})
        self.assertEqual((result.returncode, result.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
