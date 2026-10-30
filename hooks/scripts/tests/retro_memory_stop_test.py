"""Reject malformed retrospective memory counts at the native Claude Stop hook."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.loop_stall_fixture import StallGuardCase


class RetroMemoryStopTests(StallGuardCase):
    """Keep a forged count from escaping the completion gate as a hook error."""

    def test_bad_count_blocks_with_a_reason(self) -> None:
        """The Stop hook denies malformed counts and leaves its stop row unconsumed."""
        path = self.complete_fixture()
        retro_path = path.with_name("retro.json")
        retro = json.loads(retro_path.read_text())
        payload = self.payload(self.stopped("LOOP-STOP: complete"))
        for counts in ({"x": "bad"}, {"x": True}, {"x": -1}, ["bad"]):
            with self.subTest(counts=counts):
                retro["memory"]["degraded"] = {"order.record": counts}
                retro_path.write_text(json.dumps(retro))
                result = self.run_hook("loop_stall_guard", payload)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("retro_memory_invalid", result.stderr)
                self.assertFalse(json.loads(path.read_text())["stops"][-1]["consumed"])

    def test_valid_count_remains_a_disclosure(self) -> None:
        """A real integer count is printed and permits the completed Stop."""
        path = self.complete_fixture()
        retro_path = path.with_name("retro.json")
        retro = json.loads(retro_path.read_text())
        retro["memory"]["degraded"] = {"order.record": {"muninn_absent": 1}}
        retro_path.write_text(json.dumps(retro))
        result = self.run_hook("loop_stall_guard", self.payload(self.stopped("LOOP-STOP: complete")))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 order.record event(s)", result.stdout)


if __name__ == "__main__":
    unittest.main()
