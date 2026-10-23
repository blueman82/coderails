"""Verify the stop-block and conversion counters against synthetic trace rows."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.lib.stop_counters import REASONS, count_reasons


def line(code: str, event: str, ts: str = "2026-10-05T10:00:00+00:00") -> str:
    """One trace JSON line."""
    return json.dumps({"event_id": event, "ts": ts, "reason_code": code}) + "\n"


class StopCounterTests(unittest.TestCase):
    """Counts come from both trace files, are deduped per event, and ignore everything else."""

    def test_counts_blocks_and_conversions_once_per_event(self) -> None:
        """Trace rows and recovery-trace rows are tallied; torn lines, unknown codes and --since are handled."""
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.assertEqual(set(count_reasons(root)), set(REASONS))
            (root / "S1").mkdir()
            (root / "S1/trace.jsonl").write_text(
                line("stop_row_missing", "a") * 2
                + line("stale_stop_row", "b")
                + "{torn\n"
                + line("other", "c")
                + line("stop_row_missing", "old", ts="2026-01-01T00:00:00+00:00")
            )
            (root / "p/S1").mkdir(parents=True)
            (root / "p/S1/recovery-trace.jsonl").write_text(
                line("convert_ok", "d") + line("convert_refused_active_wave_ambiguous", "e") + line("convert_ok", "f")
            )
            counts = count_reasons(root)
            self.assertEqual((counts["stop_row_missing"], counts["stale_stop_row"], counts["convert_ok"]), (2, 1, 2))
            self.assertEqual(counts["convert_refused_active_wave_ambiguous"], 1)
            self.assertEqual(count_reasons(root, "2026-06-01")["stop_row_missing"], 1)


if __name__ == "__main__":
    unittest.main()
