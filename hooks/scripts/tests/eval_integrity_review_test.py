"""Phase F review-round regressions: re-freeze laundering, loop cmd execution, downgrade, progress, reader, trace."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.loop_evals import read_loop_evals_result
from hooks.scripts.tests.eval_integrity_test import Base, code_of
from hooks.scripts.tests.lib.post_evals_fixture import ArtifactCase, command
from scripts.lib import eval_trace
from scripts.lib.eval_execution import record_smoke
from scripts.lib.eval_integrity import append_amendment, verify_suite
from scripts.post_evals import grade_loop


class ReaderMessageTests(ArtifactCase):
    """Tamper refusal in the completion reader names its reason."""

    def setUp(self) -> None:
        """Freeze and grade a loop-scope suite."""
        super().setUp()
        self.data.update(scope="loop")
        self.save()
        record_smoke(self.path)
        grade_loop(self.path)

    def test_guard_message_names_reason_and_trace(self) -> None:
        """The Stop-hook text carries the code and does not just say 'run grade-loop'."""
        from hooks.scripts.lib.loop_state_common import LoopState
        from hooks.scripts.loop_state_guard import completion_evals

        self.data = self.reload()
        self.data["evals"][0]["cmd"] = command("raise SystemExit(0)")
        self.save()
        state = LoopState(
            path=self.directory / "progress.json",
            session="s",
            invocations=0,
            data={"schema_version": 3, "session_id": "s", "loop_id": "l", "work_units": {"a": 1}, "status": "complete"},
        )
        message = completion_evals(state)
        self.assertIn("reason=suite_hash_mismatch", message)
        self.assertIn("eval_trace.jsonl", message)
        self.assertNotIn("missing a valid grading stamp", message)


class ReFreezeTests(Base):
    """smoke-run must not launder an edited oracle into a fresh frozen_hash."""

    def test_resmoke_after_unrecorded_edit_refused(self) -> None:
        """Test resmoke after unrecorded edit refused."""
        before = self.data["frozen_hash"]
        self.edit_cmd(command("raise SystemExit(0)"))
        self.assertEqual(code_of(self, lambda: record_smoke(self.path)), "suite_hash_mismatch")
        self.assertEqual(self.reload()["frozen_hash"], before)
        self.assertEqual(code_of(self, lambda: grade_loop(self.path)), "suite_hash_mismatch")

    def test_resmoke_after_amend_allowed(self) -> None:
        """Test resmoke after amend allowed."""
        self.edit_cmd(command("print('v2')"))
        append_amendment(self.data, "E1", "why", "me")
        self.save()
        record_smoke(self.path)
        self.assertEqual(verify_suite(self.reload()), "verified")

    def test_resmoke_unchanged_is_idempotent(self) -> None:
        """Test resmoke unchanged is idempotent."""
        before = self.data["frozen_hash"]
        record_smoke(self.path)
        self.assertEqual(self.reload()["frozen_hash"], before)


class LoopCmdExecutionTests(ArtifactCase):
    """grade-loop re-executes cmd, not only the control."""

    def frozen_with(self, cmd: str) -> None:
        """Freeze a suite whose cmd is the given text, status pass."""
        self.data["evals"][0]["cmd"] = cmd
        self.save()
        record_smoke(self.path)

    def test_failing_cmd_with_pass_status_refused(self) -> None:
        """Test failing cmd with pass status refused."""
        self.frozen_with(command("raise SystemExit(7)"))
        self.assertEqual(code_of(self, lambda: grade_loop(self.path)), "pass_exit_nonzero")
        self.assertNotIn("grading", self.reload())

    def test_cmd_environmental_refused(self) -> None:
        """Test cmd environmental refused."""
        self.frozen_with("definitely-not-a-command-xyz")
        self.assertEqual(code_of(self, lambda: grade_loop(self.path)), "cmd_env")


class DowngradeTests(Base):
    """Partial stripping of the hash is detected; full stripping is a documented residual."""

    def test_strip_frozen_hash_after_grade_detected(self) -> None:
        """Test strip frozen hash after grade detected."""
        grade_loop(self.path)
        self.data = self.reload()
        self.data["evals"][0]["cmd"] = command("raise SystemExit(0)")
        self.data.pop("frozen_hash")
        self.save()
        self.assertEqual(code_of(self, lambda: verify_suite(self.reload(), stamped=True)), "integrity_stripped")

    def test_strip_hash_and_graded_tombstones_is_documented_residual(self) -> None:
        """Test strip hash and graded tombstones is documented residual."""
        grade_loop(self.path)
        self.data = self.reload()
        self.data.pop("frozen_hash")
        for key in ("suite_hash", "integrity", "chain_len", "chain_head"):
            self.data["grading"].pop(key)
        if "signature" in self.data:  # a leftover signature is now refused; the residual is the fully unsigned strip
            self.assertEqual(code_of(self, lambda: verify_suite(self.data, stamped=True)), "integrity_stripped")
            self.data.pop("signature")
        self.assertEqual(verify_suite(self.data, stamped=True), "legacy_unhashed")


class ProgressHardeningTests(ArtifactCase):
    """The identity source cannot be redirected or blanked."""

    def test_symlinked_progress_refused(self) -> None:
        """Test symlinked progress refused."""
        other = self.directory / "other-progress.json"
        other.write_text('{"schema_version":3,"session_id":"OTHER","loop_id":"OL"}')
        (self.directory / "progress.json").unlink()
        (self.directory / "progress.json").symlink_to(other)
        self.assertEqual(code_of(self, lambda: grade_loop(self.path)), "progress_foreign")
        self.assertNotIn("session_id", self.reload())

    def test_blank_ids_refused(self) -> None:
        """Test blank ids refused."""
        (self.directory / "progress.json").write_text('{"schema_version":3,"session_id":" ","loop_id":"l"}')
        self.assertEqual(code_of(self, lambda: grade_loop(self.path)), "progress_unparseable")


class TraceDedupTests(ArtifactCase):
    """Counters track distinct suite states, not hook call frequency."""

    def test_duplicate_event_is_one_row_and_counted_once(self) -> None:
        """Hook polling must not inflate counters: same suite sha + reason is one row."""
        for _ in range(3):
            eval_trace.emit(self.path, "loop-evals-read", "legacy", "legacy_unhashed")
        lines = (self.directory / "eval_trace.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 1)
        self.data["task_ref"] = "changed"
        self.save()
        eval_trace.emit(self.path, "loop-evals-read", "legacy", "legacy_unhashed")
        self.assertEqual(len((self.directory / "eval_trace.jsonl").read_text().splitlines()), 2)

    def test_sink_is_capped(self) -> None:
        """Test sink is capped."""
        sink = self.directory / "eval_trace.jsonl"
        sink.write_text("x" * (eval_trace.MAX_SINK_BYTES + 1))
        eval_trace.emit(self.path, "grade-loop", "refuse", "control_passes")
        self.assertEqual(sink.stat().st_size, eval_trace.MAX_SINK_BYTES + 1)


class LoopReaderLegacyTests(ArtifactCase):
    """Repeated reads of one legacy suite add one trace row."""

    def test_three_reads_one_row(self) -> None:
        """Test three reads one row."""
        self.data.update(scope="loop")
        self.save()
        grade_loop(self.path)
        for _ in range(3):
            self.assertEqual(read_loop_evals_result(Path(self.directory)), "GO")
        rows = (self.directory / "eval_trace.jsonl").read_text().splitlines()
        self.assertEqual(sum("loop-evals-read" in row for row in rows), 1)


if __name__ == "__main__":
    unittest.main()
