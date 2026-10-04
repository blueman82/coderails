"""Count config/wiki-schema reason codes from trace rows, tolerating torn lines."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
