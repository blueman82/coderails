"""Keep source-quality feedback advisory and empty input silent."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.native_hook_test_support import HookCase


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


if __name__ == "__main__":
    unittest.main()
