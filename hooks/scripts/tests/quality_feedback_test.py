"""Keep source-quality feedback advisory and empty input silent."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts import quality_feedback
from hooks.scripts.tests.native_hook_test_support import HookCase

ROOT = Path(__file__).resolve().parents[3]


class QualityFeedbackTests(HookCase):
    """Inspect one actual source defect through the native feedback hook."""

    def setUp(self) -> None:
        """Keep installed tool discovery while inherited writable fixture paths remain private."""
        super().setUp()
        self.environment["HOME"] = os.environ["HOME"]

    def test_external_only_failure_is_disclosed(self) -> None:
        """A missing module docstring fails external tools even with no built-in findings."""
        bad = self.directory / "external.py"
        bad.write_text("VALUE = 1\n", encoding="utf-8")
        result = self.invoke("quality_feedback", {"tool_input": {"file_path": str(bad)}})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("external quality checks failed", result.stdout)

    def test_unusable_checker_json_and_failed_clean_claim_are_disclosed(self) -> None:
        """Malformed structured results and nonzero empty results never mean clean."""
        bad = self.directory / "bad.py"
        bad.write_text('"""Fixture."""\n')
        payload = {"tool_input": {"file_path": str(bad)}}
        for stdout, code in (
            ("", 0),
            ("not-json", 0),
            ('{"findings": {}}', 0),
            ('{"scanned": 1, "findings": [], "external_ok": true}', 1),
        ):
            with (
                self.subTest(stdout=stdout, code=code),
                mock.patch.object(quality_feedback, "read_payload", return_value=payload),
                mock.patch(
                    "hooks.scripts.quality_feedback.subprocess.run",
                    return_value=subprocess.CompletedProcess([], code, stdout, "checker diagnostic"),
                ),
                mock.patch("builtins.print") as output,
            ):
                self.assertEqual(quality_feedback.main(), 0)
                self.assertTrue(output.called, "unusable checker output was silently clean")

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
        with (
            mock.patch.object(quality_feedback, "read_payload", return_value={"tool_input": {"file_path": str(good)}}),
            mock.patch(
                "hooks.scripts.quality_feedback.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    [], 0, '{"scanned": 1, "findings": [], "external_ok": true}', ""
                ),
            ),
            mock.patch("builtins.print") as output,
        ):
            self.assertEqual(quality_feedback.main(), 0)
            output.assert_not_called()


if __name__ == "__main__":
    unittest.main()
