"""Final Stop and ambiguous memory checks for assembled retrospectives."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from hooks.scripts.lib.graph_stops import record_stop  # noqa: E402
from scripts.tests.fake_muninn_case import SESSION  # noqa: E402
from scripts.tests.retro_test import Base  # noqa: E402


class FinalStop(Base):
    """Preserve preparation evidence across the last owned Stop declaration."""

    def test_complete_stop_after_preparation_preserves_bound_evidence(self) -> None:
        """The final owned stop follows preparation; an unrelated stop edit still invalidates it."""
        state = self.state()
        state["graph"]["nodes"]["U3[1]"]["status"] = "skipped"
        state["graph"]["nodes"]["U3[1]"]["outcome"] = "skipped"
        self.put(record_stop(state, SESSION, "hard-stop", "environment_blocked", "earlier stop")["state"])
        self.ready()
        stopped = record_stop(self.state(), SESSION, "complete", "work_complete", "verified work")["state"]
        self.put(stopped)
        self.assertEqual(self.gate(), [])
        stopped["stops"][0]["reason"] = "changed after recording"
        self.put(stopped)
        with self.assertRaisesRegex(ValueError, "retro_steps_missing.*orders_prepared"):
            self.gate()

    def test_ambiguous_memory_write_cannot_be_attested_as_flushed(self) -> None:
        """A syncing decision gives a reason-coded refusal and leaves no assembled retro."""
        self.decide()
        self.dispose()
        state = self.state()
        state["decisions_absorbed"][0]["muninn"] = {"state": "syncing"}
        self.put(state)
        self.prepare()
        code, result = self.assemble()
        self.assertEqual((code, result["reason_code"]), (3, "decision_sync_unknown"))
        self.assertFalse((self.dir / "retro.json").exists())


if __name__ == "__main__":
    unittest.main()
