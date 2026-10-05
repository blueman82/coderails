"""Verify the recorded-stop counters against synthetic loop state and trace rows."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "graph_alignment_stops.py"


def write(path: Path, text: str) -> None:
    """Create parents and write a UTF-8 file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def row(reason: str, event: str) -> str:
    """Return one trace JSON line."""
    return json.dumps({"event_id": event, "command": "c", "outcome": "fallback", "reason_code": reason}) + "\n"


class GraphAlignmentStopsTests(unittest.TestCase):
    """Counters read stops[] from loop state and fallback reason codes from trace rows."""

    def run_script(self, root: Path) -> dict[str, object]:
        """Run the helper against an isolated home and loop-state root."""
        env = {**os.environ, "HOME": str(root), "CLAUDE_AGENTIC_LOOP_DIR": str(root / "loops")}
        env.pop("CODERAILS_AGENTIC_LOOP_DIR", None)
        result = subprocess.run([sys.executable, str(SCRIPT), "--json"], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return dict(json.loads(result.stdout))

    def test_counts_recorded_consumed_and_legacy_fallbacks(self) -> None:
        """Torn files, a malformed stops key, duplicate trace event ids, and an empty root never raise."""
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.assertEqual(
                self.run_script(root),
                {"stops_recorded": 0, "stops_consumed": 0, "legacy_text_parse": 0, "legacy_log_parse": 0},
            )
            stops = [{"consumed": True}, {"consumed": False}, "junk"]
            write(root / "loops/p/S1/progress.json", json.dumps({"stops": stops}))
            write(root / "loops/p/S2/progress.json", '{"stops": "torn"}')
            write(root / "loops/p/S3/progress.json", "{torn")
            write(root / "loops/S1/trace.jsonl", row("legacy_text_parse", "a") * 2 + row("legacy_log_parse", "b"))
            write(root / "loops/S2/trace.jsonl", row("legacy_text_parse", "c") + "{torn\n" + row("other", "d"))
            counts = self.run_script(root)
            self.assertEqual(
                counts, {"stops_recorded": 2, "stops_consumed": 1, "legacy_text_parse": 2, "legacy_log_parse": 1}
            )


if __name__ == "__main__":
    unittest.main()
