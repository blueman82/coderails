"""The routine merge stage must bind its PR to the validated branch and policy."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.tests.routine_run_test import RoutineCase


class MergeScopeTests(RoutineCase):
    """A valid gate executable cannot deliver a foreign PR."""

    def test_merge_gate_cannot_target_another_pr(self) -> None:
        """A staged docs branch cannot deliver a different PR through a valid merge script."""
        self.write("docs/a.md", "x\n")
        self.commit()
        self.assertEqual(self.advance_to_manifest_check().returncode, 0)
        for name in ("push", "review", "post_review", "post_evals"):
            self.assertEqual(self.stage(name).returncode, 0, name)
        before = self.ran.read_text().count("ran")
        result = self.run_tool("run-gate", "merge", "--", str(self.plugin / "scripts/merge.py"), "8")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.ran.read_text().count("ran"), before)
        self.assertEqual(self.rows()[-1]["reason_code"], "gate_argv_not_allowed")


if __name__ == "__main__":
    unittest.main()
