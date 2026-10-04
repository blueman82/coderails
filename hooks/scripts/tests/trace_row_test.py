#!/usr/bin/env python3
"""Pin the non-authoritative, fail-open trace row writer."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.trace_row import append_row, trace_path


class TraceRowTests(unittest.TestCase):
    """One row per event, never raises, never stores raw input."""

    def setUp(self) -> None:
        """Isolate the loop dir."""
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def test_row_schema_and_hashed_inputs(self) -> None:
        """Rows carry the schema fields, a uuid event_id and only the sha256 of inputs."""
        ok = append_row("gate", "blocked", "some_reason", "s1", inputs={"cmd": "SECRET"}, base=self.base)
        self.assertTrue(ok)
        raw = (self.base / "s1" / "trace.jsonl").read_text()
        self.assertNotIn("SECRET", raw)
        row = json.loads(raw)
        for key in ("schema_version", "event_id", "session_id", "loop_id", "ts", "command", "outcome", "reason_code"):
            self.assertIn(key, row)
        self.assertEqual(row["inputs"]["cmd"], hashlib.sha256(b"SECRET").hexdigest())
        self.assertIsNone(row["loop_id"])
        self.assertEqual(row["session_id"], "s1")

    def test_event_ids_unique_and_append_only(self) -> None:
        """Two appends give two lines with different event ids."""
        append_row("g", "o", "r", "s1", base=self.base)
        append_row("g", "o", "r", "s1", base=self.base)
        rows = [json.loads(x) for x in (self.base / "s1" / "trace.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["event_id"], rows[1]["event_id"])

    def test_unwritable_dir_fails_open(self) -> None:
        """An unwritable base returns False without raising."""
        blocker = self.base / "file"
        blocker.write_text("x")
        self.assertFalse(append_row("g", "o", "r", "s1", base=blocker / "sub"))

    def test_unsafe_session_id_refused_not_sanitised(self) -> None:
        """Ids with a slash or dotdot are refused so two ids never collide."""
        for bad in ("a/b", "..", "a..b", ""):
            with self.subTest(bad=bad):
                self.assertFalse(append_row("g", "o", "r", bad, base=self.base))
        self.assertEqual(list(self.base.iterdir()), [])

    def test_env_dir_default(self) -> None:
        """CLAUDE_AGENTIC_LOOP_DIR picks the base when none is passed."""
        old = os.environ.get("CLAUDE_AGENTIC_LOOP_DIR")
        os.environ["CLAUDE_AGENTIC_LOOP_DIR"] = str(self.base)

        def restore() -> None:
            if old is None:
                os.environ.pop("CLAUDE_AGENTIC_LOOP_DIR", None)
            else:
                os.environ["CLAUDE_AGENTIC_LOOP_DIR"] = old

        self.addCleanup(restore)
        self.assertEqual(trace_path("s9"), self.base / "s9" / "trace.jsonl")


if __name__ == "__main__":
    unittest.main()
