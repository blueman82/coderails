"""Count config/wiki-schema reason codes from trace rows, tolerating torn lines."""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib.config_counters import REASONS, count_reasons


class CounterTests(unittest.TestCase):
    """Only the stable reason codes are counted."""

    def test_counts_and_ignores_noise(self) -> None:
        """Torn lines, other commands and other codes never raise or count."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sessions = (("a", ["config_unknown_key", "config_unknown_key", "other"]), ("b", ["wiki_schema_missing"]))
            for session, codes in sessions:
                (root / session).mkdir()
                lines = [json.dumps({"reason_code": code}) for code in codes] + ["{torn", "[1]"]
                (root / session / "trace.jsonl").write_text("\n".join(lines) + "\n")
            self.assertEqual(
                count_reasons(root),
                {**dict.fromkeys(REASONS, 0), "config_unknown_key": 2, "wiki_schema_missing": 1},
            )
            self.assertEqual(count_reasons(root / "absent"), dict.fromkeys(REASONS, 0))

    def test_since_scopes_and_measure_reports_rows(self) -> None:
        """Negative control: unscoped counts include old rows; measure_graph_alignment sees config rows too."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a").mkdir()
            rows = [
                {"event_id": ts, "command": "config", "outcome": "warned", "ts": ts, "reason_code": "config_bad_type"}
                for ts in ("2026-01-01T00:00:00+00:00", "2026-10-05T00:00:00+00:00")
            ]
            (root / "a/trace.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            self.assertEqual(count_reasons(root)["config_bad_type"], 2)
            self.assertEqual(count_reasons(root, "2026-06-01")["config_bad_type"], 1)
            with patch.dict(os.environ, {"CLAUDE_AGENTIC_LOOP_DIR": temporary}):
                sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
                trace = importlib.import_module("measure_graph_alignment").trace_counts()
            self.assertGreaterEqual(trace["by_reason"]["config/warned/config_bad_type"], 2)  # + any real-home rows


if __name__ == "__main__":
    unittest.main()
