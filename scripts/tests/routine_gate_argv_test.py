"""Routine gate commands must perform the pinned operation before advancing."""

from __future__ import annotations

import sys

from scripts import routine_run
from scripts.tests.routine_run_test import REPO, RoutineCase


class GateArgvTests(RoutineCase):
    """Check help and read-only command forms at the gate boundary."""

    def test_help_cannot_advance_a_gate_even_when_the_command_exits_zero(self) -> None:
        """A zero-exit help invocation is never delivery evidence."""
        self.write("docs/a.md", "x\n")
        self.commit()
        self.assertEqual(self.advance_to_manifest_check().returncode, 0)
        result = self.run_tool("run-gate", "push", "--", str(self.plugin / "scripts/push.py"), "--help")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("gate_argv_not_allowed", result.stderr)
        self.assertEqual(self.rows()[-1]["reason_code"], "gate_argv_not_allowed")
        self.assertFalse(self.ran.exists())

    def test_nonposting_forms_are_rejected_for_each_pinned_gate(self) -> None:
        """The path-only check cannot accept help or validation as posting."""
        for script in ("push.py", "post_review.py", "post_evals.py", "merge.py"):
            with self.subTest(script=script):
                path = str(REPO / "scripts" / script)
                self.assertFalse(routine_run.gate_allowed(script, [sys.executable, path, "--help"]))
                self.assertFalse(routine_run.gate_allowed(script, [path, "-h"]))
        for script in ("post_review.py", "post_evals.py"):
            with self.subTest(script=script):
                path = str(REPO / "scripts" / script)
                allowed = routine_run.gate_allowed(script, [sys.executable, path, "validate-structure", "suite.json"])
                self.assertFalse(allowed)
