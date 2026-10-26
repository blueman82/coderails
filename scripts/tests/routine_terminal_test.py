"""Routine terminal rows remain honest when predicate reads or state writes fail."""

from __future__ import annotations

import os
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

    def test_child_token_is_exact_and_manual_begin_still_works(self) -> None:
        """A bad child token writes nothing; a valid one binds the row; manual runs generate their own ID."""
        with mock.patch.dict(os.environ, {"CODERAILS_ROUTINE_RUN_ID": "bad"}):
            self.assertEqual(self.run_tool("begin").returncode, 2)
        self.assertEqual(self.rows(), [])
        with mock.patch.dict(os.environ, {"CODERAILS_ROUTINE_RUN_ID": "0123456789abcdef"}):
            self.assertEqual(self.run_tool("begin").returncode, 0)
            self.assertEqual(self.run_tool("finish", "no_drift").returncode, 0)
        self.assertEqual(self.rows()[0]["run_id"], "0123456789abcdef")
        with mock.patch.dict(os.environ):
            os.environ.pop("CODERAILS_ROUTINE_RUN_ID", None)
            self.assertEqual(self.run_tool("begin").returncode, 0)
            self.assertEqual(self.run_tool("finish", "no_drift").returncode, 0)
            self.assertEqual(self.run_tool("begin").returncode, 0)
            self.assertEqual(self.run_tool("stage", "fetch_branch").returncode, 0)
        self.assertEqual(len(self.rows()[-1]["run_id"]), 12)

    def test_foreign_child_cannot_finish_or_abort_active_run(self) -> None:
        """A different or missing child token cannot mutate a dashboard-owned run."""
        owner = "0123456789abcdef"
        with mock.patch.dict(os.environ, {"CODERAILS_ROUTINE_RUN_ID": owner}):
            self.assertEqual(self.run_tool("begin").returncode, 0)
        before = self.rows()
        for foreign in ("fedcba9876543210", None):
            with self.subTest(foreign=foreign), mock.patch.dict(os.environ):
                if foreign is None:
                    os.environ.pop("CODERAILS_ROUTINE_RUN_ID", None)
                else:
                    os.environ["CODERAILS_ROUTINE_RUN_ID"] = foreign
                for command in (("finish", "no_drift"), ("abort", "incomplete-run"), ("stage", "fetch_branch")):
                    result = self.run_tool(*command)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("run_id_mismatch", result.stderr)
        self.assertEqual(self.rows(), before)
        with mock.patch.dict(os.environ, {"CODERAILS_ROUTINE_RUN_ID": owner}):
            self.assertEqual(self.run_tool("finish", "no_drift").returncode, 0)

    def test_merged_incomplete_row_survives_state_save_failure(self) -> None:
        """A save error after a remote merge still leaves a red non-abort row."""
        self.assertEqual(self.run_tool("begin").returncode, 0)
        run = routine_run.Run("docs-sync", str(self.log))
        self.assertTrue(run.load())
        with mock.patch.object(run, "save", side_effect=OSError("disk full")), self.assertRaises(OSError):
            run.incomplete("merged_incomplete")
        self.assertEqual(self.rows()[-1]["reason_code"], "merged_incomplete")
        self.assertIn("incomplete=merged", self.log.read_text())
        self.assertNotIn("run_abort", [row["outcome"] for row in self.rows()])


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
