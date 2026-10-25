"""Verify the graph-spec counters against synthetic trace rows."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.lib.spec_counters import REASONS, count_reasons


def line(code: str, event: str, ts: str = "2026-10-05T10:00:00+00:00") -> str:
    """One trace JSON line."""
    return json.dumps({"event_id": event, "ts": ts, "reason_code": code}) + "\n"


class SpecCounterTests(unittest.TestCase):
    """Counts come from recovery-trace rows, are deduped per event and ignore everything else."""

    def test_counts_each_code_once_per_event(self) -> None:
        """A shared event id counts once; torn lines, unknown codes and rows before --since are ignored."""
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.assertEqual(set(count_reasons(root)), set(REASONS))
            (root / "p/S1").mkdir(parents=True)
            (root / "p/S1/recovery-trace.jsonl").write_text(
                line("spec_edge_missing", "a")
                + line("skip_when_met", "b") * 3
                + line("instantiate_ok", "c")
                + "{torn\n"
                + line("other", "d")
                + line("spec_edge_missing", "old", ts="2026-01-01T00:00:00+00:00")
            )
            counts = count_reasons(root)
            self.assertEqual(
                (counts["spec_edge_missing"], counts["skip_when_met"], counts["instantiate_ok"]), (2, 1, 1)
            )
            self.assertEqual(count_reasons(root, "2026-06-01")["spec_edge_missing"], 1)


if __name__ == "__main__":
    unittest.main()
