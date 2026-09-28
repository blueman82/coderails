#!/usr/bin/env python3
"""Verify loop ownership, registration grace, rearming, and exact completion eval bindings."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.hook_test_support import HookTestCase
from scripts.lib.eval_artifact import grading_checksum


class LoopStateGuardTests(HookTestCase):
    """Keep state-presence enforcement and completion evidence fail-closed."""

    def test_cheap_skips_and_owned_state(self) -> None:
        """Non-loop, no transcript, recursive stop, and session-owned active state pass."""
        self.assertEqual(self.run_hook("loop_state_guard", {}).returncode, 0)
        payload = self.payload(self.transcript("text", 0))
        self.assertEqual(self.run_hook("loop_state_guard", payload).returncode, 0)
        payload = {**self.payload(self.transcript()), "stop_hook_active": True}
        self.assertEqual(self.run_hook("loop_state_guard", payload).returncode, 0)
        self.progress()
        self.assertEqual(self.run_hook("loop_state_guard", self.payload(self.transcript())).returncode, 0)

    def test_legacy_state_cannot_disable_presence_enforcement(self) -> None:
        """Only schema v3 can establish active ownership or the complete off-switch."""
        payload = self.payload(self.transcript())
        for version in (None, 1, 2):
            for status in ("complete", "in-progress"):
                self.progress(status, 1, schema_version=version)
                with self.subTest(version=version, status=status):
                    self.assertEqual(self.run_hook("loop_state_guard", payload).returncode, 2)

    def test_absent_grace_is_session_and_invocation_scoped(self) -> None:
        """Only a prior absent block for the exact session/invocation gets a grace release."""
        payload = self.payload(self.transcript())
        first = self.run_hook("loop_state_guard", payload)
        self.assertEqual(first.returncode, 2)
        self.assertIn("no progress.json", first.stderr)
        self.assertEqual(self.run_hook("loop_state_guard", payload).returncode, 0)
        payload["session_id"] = "S2"
        self.assertEqual(self.run_hook("loop_state_guard", payload).returncode, 2)
        payload = self.payload(self.transcript(invocations=2))
        self.assertEqual(self.run_hook("loop_state_guard", payload).returncode, 2)

    def test_wrong_owner_and_rearmed_completion_never_get_absent_grace(self) -> None:
        """Wrong session and completion ordinal mismatch block repeatedly."""
        path = self.progress("complete", 0)
        payload = self.payload(self.transcript())
        for _ in range(2):
            self.assertEqual(self.run_hook("loop_state_guard", payload).returncode, 2)
        document = json.loads(path.read_text())
        document["session_id"] = "other"
        document["status"] = "in-progress"
        path.write_text(json.dumps(document))
        for _ in range(2):
            result = self.run_hook("loop_state_guard", payload)
            self.assertEqual(result.returncode, 2)
            self.assertIn("other", result.stderr)
        self.progress("complete", 1)
        self.assertEqual(self.run_hook("loop_state_guard", payload).returncode, 0)

    def test_completion_evals_stale_unjustified_frozen_and_unstamped(self) -> None:
        """A work-unit-bearing completion requires a grade for its exact loop revision."""
        path = self.progress("complete", 1, work_units={"U3[1]": {"status": "done"}})
        payload = self.payload(self.transcript())
        self.assertEqual(self.run_hook("loop_state_guard", payload).returncode, 2)
        suite_path = path.with_name("evals.json")
        suite: dict[str, Any] = {
            "scope": "loop",
            "verification_level": 0,
            "verification_justification": "no executable change",
            "result": "GO",
            "evals": [],
            "session_id": "S1",
            "loop_id": "loop-test",
            "revision": 1,
        }
        suite_path.write_text(json.dumps(suite))
        self.assertIn("grading stamp", self.run_hook("loop_state_guard", payload).stderr)
        suite["grading"] = {"by": "post_evals.py grade-loop", "checksum": grading_checksum(suite_path, "GO")}
        suite_path.write_text(json.dumps(suite))
        self.assertEqual(self.run_hook("loop_state_guard", payload).returncode, 0)
        suite["revision"] = 2
        suite_path.write_text(json.dumps(suite))
        self.assertIn("STALE", self.run_hook("loop_state_guard", payload).stderr)
        suite["revision"] = 1
        suite["verification_justification"] = " "
        suite_path.write_text(json.dumps(suite))
        self.assertIn("verification_justification", self.run_hook("loop_state_guard", payload).stderr)
        suite.update(
            {
                "verification_justification": "hook",
                "verification_level": 1,
                "result": None,
                "grading": None,
                "frozen_sha": "a" * 40,
                "evals": [{"id": "E1", "priority": "P0", "mode": "agent-run"}],
            }
        )
        suite_path.write_text(json.dumps(suite))
        self.assertIn("FROZEN", self.run_hook("loop_state_guard", payload).stderr)

    def test_completed_loop_without_work_units_and_malformed_state(self) -> None:
        """Absent work-unit rosters do not require loop evals; malformed ownership blocks."""
        path = self.progress("complete", 1)
        payload = self.payload(self.transcript())
        self.assertEqual(self.run_hook("loop_state_guard", payload).returncode, 0)
        path.write_text("{bad")
        self.assertEqual(self.run_hook("loop_state_guard", payload).returncode, 2)


if __name__ == "__main__":
    unittest.main()
