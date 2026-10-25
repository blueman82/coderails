"""Verify the worker-status counters against synthetic trace rows and state."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/agentic-loop/scripts"))
import worker_status

from scripts.lib.worker_counters import REASON_CODES, count_reasons, counts


def line(code: str, event: str, ts: str = "2026-10-05T10:00:00+00:00") -> str:
    """One trace JSON line."""
    return json.dumps({"event_id": event, "ts": ts, "reason_code": code}) + "\n"


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


if __name__ == "__main__":
    unittest.main()
