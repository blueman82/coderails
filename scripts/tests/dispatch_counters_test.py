"""Verify the dispatch-envelope counters against synthetic trace rows."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/graph-semantics"))
from graph_contract import CODES

from scripts.lib.dispatch_counters import REASONS, count_reasons


def line(code: str, event: str, ts: str = "2026-10-05T10:00:00+00:00") -> str:
    """One trace JSON line."""
    return json.dumps({"event_id": event, "ts": ts, "reason_code": code}) + "\n"


class DispatchCounterTests(unittest.TestCase):
    """Counts come from recovery-trace rows, are deduped per event and ignore everything else."""

    def test_every_contract_code_is_counted(self) -> None:
        """The counter's vocabulary is the contract's closed codes plus the allow row."""
        self.assertEqual(set(REASONS), {*CODES, "dispatch_authorized"})

    def test_counts_each_code_once_per_event(self) -> None:
        """A shared event id counts once; torn lines, unknown codes and rows before --since are ignored."""
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.assertEqual(set(count_reasons(root)), set(REASONS))
            (root / "p/S1").mkdir(parents=True)
            (root / "p/S1/recovery-trace.jsonl").write_text(
                line("dispatch_replayed", "a")
                + line("role_mismatch", "b") * 3
                + line("dispatch_authorized", "c")
                + "{torn\n"
                + line("other", "d")
                + line("dispatch_replayed", "old", ts="2026-01-01T00:00:00+00:00")
            )
            counts = count_reasons(root)
            found = (counts["dispatch_replayed"], counts["role_mismatch"], counts["dispatch_authorized"])
            self.assertEqual(found, (2, 1, 1))
            self.assertEqual(count_reasons(root, "2026-06-01")["dispatch_replayed"], 1)


if __name__ == "__main__":
    unittest.main()
