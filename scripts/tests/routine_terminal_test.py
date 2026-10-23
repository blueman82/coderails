"""Routine terminal rows remain honest when predicate reads or state writes fail."""

from __future__ import annotations

import unittest
from unittest import mock

from scripts import routine_run
from scripts.tests.routine_run_test import RoutineCase, last_marker_is_green


class TerminalSaveTests(RoutineCase):
    """A durable terminal state must exist before a green log marker."""

    def test_terminal_save_failure_cannot_write_success_marker(self) -> None:
        """A failed terminal save keeps the provisional failure marker last."""
        self.assertEqual(self.run_tool("begin").returncode, 0)
        run = routine_run.Run("docs-sync", str(self.log))
        self.assertTrue(run.load())
        with mock.patch.object(run, "save", side_effect=OSError("disk full")), self.assertRaises(OSError):
            run.end("no_drift", "run_ok", "")
        self.assertEqual(self.rows()[-1]["outcome"], "run_incomplete")
        self.assertFalse(last_marker_is_green(self.log))


class RetroPredicateTerminalTests(RoutineCase):
    """A typed predicate must fail closed before promotion work begins."""

    routine = "loop-retro-promotion"

    def test_predicate_failures_abort_and_unmet_can_finish(self) -> None:
        """Each predicate failure is terminal; only a valid unmet result can close a dormant run."""
        for code in ("predicate_refused", "predicate_degraded", "predicate_unavailable"):
            with self.subTest(code=code):
                self.assertEqual(self.run_tool("begin", "--new").returncode, 0)
                self.assertEqual(self.run_tool("abort", code).returncode, 0)
                self.assertEqual((self.rows()[-1]["outcome"], self.rows()[-1]["reason_code"]), ("run_abort", code))
                self.assertFalse(last_marker_is_green(self.log))
        self.assertEqual(self.run_tool("begin", "--new").returncode, 0)
        self.assertEqual(self.run_tool("finish", "no_drift").returncode, 0)
        self.assertTrue(last_marker_is_green(self.log))


if __name__ == "__main__":
    unittest.main()
