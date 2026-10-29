"""Verify the worker-status counters against synthetic trace rows and state."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/agentic-loop/scripts"))
import worker_status

from scripts.lib.worker_counters import REASON_CODES, count_reasons, counts, main


def line(code: str, event: str, ts: str = "2026-10-05T10:00:00+00:00") -> str:
    """One trace JSON line."""
    return json.dumps({"event_id": event, "ts": ts, "reason_code": code}) + "\n"


def decision_line(event: str, outcome: str = "recorded") -> str:
    """One actual decision_record trace row."""
    return (
        json.dumps(
            {
                "event_id": event,
                "ts": "2026-10-05T10:00:00+00:00",
                "command": "decision.record",
                "outcome": outcome,
                "reason_code": "ok" if outcome == "recorded" else "record_decision_refused_field",
            }
        )
        + "\n"
    )


class WorkerCounterTests(unittest.TestCase):
    """Counts come from trace rows and progress.json, deduped per event, ignoring everything else."""

    def test_vocabulary_covers_every_refusal_and_status(self) -> None:
        """The counter knows each refusal code the pre-processor can raise and each recorded status."""
        self.assertTrue(set(worker_status.REFUSAL_CODES) <= set(REASON_CODES))
        for status in worker_status.STATUSES:
            self.assertIn(f"worker_status_{status.lower()}", REASON_CODES)

    def test_counts_rows_dedupe_and_pending(self) -> None:
        """Rows count once per event, torn and unknown rows are ignored, --since filters, pending reads state."""
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            loop = root / "proj/S1"
            loop.mkdir(parents=True)
            (loop / "recovery-trace.jsonl").write_text(
                line("worker_status_bad_field", "a")
                + line("final_report_invalid", "b") * 3
                + line("worker_status_needs_decision", "c")
                + "{torn\n"
                + line("other", "d")
                + line("worker_status_bad_field", "old", ts="2026-01-01T00:00:00+00:00")
            )
            rows = [{"decision_pending": True}, {"decision_pending": False}, {"decision_pending": True}]
            (loop / "progress.json").write_text(json.dumps({"worker_statuses": rows}))
            found = count_reasons(root)
            self.assertEqual(
                (found["worker_status_bad_field"], found["final_report_invalid"], found["pending_statuses"]), (2, 1, 2)
            )
            self.assertEqual(count_reasons(root, "2026-06-01")["worker_status_bad_field"], 1)
            self.assertEqual(counts([root, root])["worker_status_needs_decision"], 2)

    def test_decision_recorded_counts_only_durable_session_trace(self) -> None:
        """A local recorded decision counts even if later Muninn sync degrades."""
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            loop = root / "proj/S1"
            loop.mkdir(parents=True)
            (loop / "trace.jsonl").write_text(
                decision_line("stored") * 2
                + decision_line("refused", "refused")
                + json.dumps(
                    {"event_id": "sync", "command": "decision.sync", "outcome": "degraded", "reason_code": "ok"}
                )
                + "\n"
            )
            self.assertEqual(count_reasons(root)["decision_recorded"], 1)

    def test_cli_uses_codex_loop_root_when_claude_root_is_absent(self) -> None:
        """Codex-only configuration reads the same root as the session trace writer."""
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            loop = root / "session"
            loop.mkdir()
            (loop / "trace.jsonl").write_text(decision_line("stored"))
            output = io.StringIO()
            with (
                patch.dict(os.environ, {"CODERAILS_AGENTIC_LOOP_DIR": name, "CLAUDE_AGENTIC_LOOP_DIR": ""}),
                patch.object(sys, "argv", ["worker_counters.py"]),
                redirect_stdout(output),
            ):
                self.assertEqual(main(), 0)
            self.assertEqual(json.loads(output.getvalue())["decision_recorded"], 1)


if __name__ == "__main__":
    unittest.main()
