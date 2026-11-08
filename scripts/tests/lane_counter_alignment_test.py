"""Lane counters use the measured trace summary and keep recovery-only events."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.lib.trace_counters import measured_reasons  # noqa: E402


def line(event: str, command: str, outcome: str, reason: str) -> str:
    """Make one trace row with only the fields that the counters use."""
    return (
        json.dumps(
            {"event_id": event, "ts": "2026-10-25", "command": command, "outcome": outcome, "reason_code": reason}
        )
        + "\n"
    )


class LaneCounterAlignmentTests(unittest.TestCase):
    """Read actual measurement JSON through each counter CLI."""

    def test_measurement_pipe_keeps_trace_and_recovery_counts(self) -> None:
        """The piped summary and recovery file each contribute one independent event."""
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            loop = root / "project/session"
            loop.mkdir(parents=True)
            (root / "session").mkdir()
            (root / "session/trace.jsonl").write_text(
                line("trace-1", "guard", "refused", "stop_row_missing")
                + line("trace-2", "plan", "refused", "spec_edge_missing")
                + line("trace-3", "dispatch", "refused", "dispatch_replayed")
                + line("trace-4", "record-wave", "refused", "final_report_invalid")
            )
            (loop / "recovery-trace.jsonl").write_text(
                line("recover-1", "convert", "ok", "convert_ok")
                + line("recover-2", "plan", "refused", "spec_edge_missing")
                + line("recover-3", "authorize-dispatch", "refused", "dispatch_replayed")
                + line("recover-4", "record-wave", "refused", "final_report_invalid")
            )
            env = {**os.environ, "CLAUDE_AGENTIC_LOOP_DIR": str(root), "CODERAILS_AGENTIC_LOOP_DIR": str(root)}
            measurement = subprocess.run(
                [sys.executable, str(ROOT / "scripts/measure_graph_alignment.py"), "--root", str(ROOT), "--json"],
                capture_output=True,
                text=True,
                env=env,
                check=True,
            ).stdout
            recovered_root = root / "recovery-only"
            recovered_loop = recovered_root / "project/session"
            recovered_loop.mkdir(parents=True)
            (recovered_loop / "recovery-trace.jsonl").write_text((loop / "recovery-trace.jsonl").read_text())
            counter_env = {**env, "CLAUDE_AGENTIC_LOOP_DIR": str(recovered_root)}
            cases = {
                "stop": {"stop_row_missing": 1, "convert_ok": 1},
                "spec": {"spec_edge_missing": 2},
                "dispatch": {"dispatch_replayed": 2},
                "worker": {"final_report_invalid": 2},
            }
            for lane, expected in cases.items():
                with self.subTest(lane=lane):
                    result = subprocess.run(
                        [sys.executable, str(ROOT / f"scripts/lib/{lane}_counters.py"), "--trace-json"],
                        input=measurement,
                        capture_output=True,
                        text=True,
                        env=counter_env,
                        check=True,
                    )
                    counts = json.loads(result.stdout)
                    for code, value in expected.items():
                        self.assertEqual(counts[code], value)

    def test_invalid_summary_is_refused(self) -> None:
        """Malformed or untyped values cannot become trusted totals."""
        for payload in ({}, {"trace": {"by_reason": {"x/y/stop_row_missing": True}}}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                measured_reasons(payload, ("stop_row_missing",))

    def test_null_pipe_refuses_instead_of_scanning_local_files(self) -> None:
        """A supplied null summary must not trigger the legacy local-scan mode."""
        with tempfile.TemporaryDirectory() as name:
            env = {**os.environ, "CLAUDE_AGENTIC_LOOP_DIR": name}
            for lane in ("stop", "spec", "dispatch", "worker"):
                with self.subTest(lane=lane):
                    result = subprocess.run(
                        [sys.executable, str(ROOT / f"scripts/lib/{lane}_counters.py"), "--trace-json"],
                        input="null",
                        capture_output=True,
                        text=True,
                        env=env,
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("missing trace summary", result.stderr)
                    self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
