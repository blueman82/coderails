"""Verify neutral eval grading and adversarial command execution contracts."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex"))
from scripts import post_evals
from scripts.lib.artifact_io import read_object
from scripts.lib.eval_execution import run_recorded, verify_execution


class EvalTests(unittest.TestCase):
    """Exercise gates independently of agent-authored result fields."""

    def test_missing_and_crashing_commands_refuse(self) -> None:
        """Environmental failures are never negative-control evidence."""
        for command, control in (("missing-coderails-command-xyz", "false"), ("true", "exit 127"), ("true", "true")):
            data = {
                "verification_level": 1,
                "evals": [{"mode": "scripted", "cmd": command, "negative_control": control}],
            }
            with self.assertRaises(ValueError):
                verify_execution(data)

    def test_stdin_and_duplicate_ids_cannot_hide_next_eval(self) -> None:
        """Execute by array position with closed stdin on every leg."""
        data = {
            "verification_level": 1,
            "evals": [
                {"id": "same", "mode": "scripted", "cmd": "cat", "negative_control": "false"},
                {"id": "same", "mode": "scripted", "cmd": "true", "negative_control": "true"},
            ],
        }
        with self.assertRaisesRegex(ValueError, "negative_control exited 0"):
            verify_execution(data)

    def test_unknown_modes_and_malformed_arrays_refuse(self) -> None:
        """Never treat unenumerable evidence as an empty successful suite."""
        malformed: list[object] = [{}, "bad", [{"mode": "Scripted"}], [{}]]
        for evals in malformed:
            with self.assertRaises(ValueError):
                verify_execution({"verification_level": 1, "evals": evals})

    def test_timeout_and_output(self) -> None:
        """Timeout kills the group and diagnostics preserve both ends."""
        self.assertEqual(run_recorded("sleep 10 & wait", timeout=0.1)[0], 142)
        code, output = run_recorded("printf 'BEGIN'; printf '%0600d' 0; printf 'END'")
        self.assertEqual(code, 0)
        self.assertTrue(output.startswith("BEGIN"))
        self.assertTrue(output.endswith("END"))
        self.assertLess(len(output), 520)

    def test_grade_computes_and_binds_identity(self) -> None:
        """Compute the result and checksum without trusting caller verdicts."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evals.json"
            progress = path.with_name("progress.json")
            progress.write_text('{"session_id":"session","loop_id":"loop","revision":7}')
            path.write_text(
                json.dumps(
                    {
                        "verification_level": 1,
                        "verification_justification": "runtime",
                        "head_sha": "abc",
                        "result": "GO",
                        "evals": [
                            {"id": "E1", "mode": "agent-run", "priority": "P0", "status": "fail", "evidence": "actual"}
                        ],
                    }
                )
            )
            self.assertEqual(post_evals.grade_loop(path), "NO-GO")
            data = read_object(path)
            self.assertEqual(data["session_id"], "session")
            self.assertEqual(data["grading"]["by"], "post_evals.py grade-loop")
            data["amendments"] = [{"why": "changed"}]
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "regraded_by"):
                post_evals.grade_loop(path)
            invalid_values: tuple[object, ...] = (123, True, [], {}, "   ")
            for invalid in invalid_values:
                data["regraded_by"] = invalid
                path.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, "regraded_by"):
                    post_evals.grade_loop(path)


if __name__ == "__main__":
    unittest.main()
