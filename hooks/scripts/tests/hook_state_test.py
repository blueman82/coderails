#!/usr/bin/env python3
"""Typed hook_state.json: exact-session nudge dedupe, log-proof grace, torn state, persisted ordinals and arms."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib import hook_state
from hooks.scripts.lib.loop_state_common import LoopState
from hooks.scripts.lib.trace_row import append_row
from hooks.scripts.tests.lib.hook_test_support import HookTestCase
from scripts.lib.state_counters import count_reasons

OFFLOAD = "Please run git push origin main yourself from your own shell."


class HookStateTests(HookTestCase):
    """Nudge dedupe and grace come from the typed file, never from discipline.log text."""

    def offload(self, session: str) -> str:
        """Run offload_push_guard for a session; return its additionalContext ('' when silent)."""
        transcript = self.directory / f"{session}.jsonl"
        message = {"type": "assistant", "message": {"content": [{"type": "text", "text": OFFLOAD}]}}
        transcript.write_text(json.dumps(message) + "\n")
        payload = {"transcript_path": str(transcript), "session_id": session, "hook_event_name": "Stop"}
        result = self.run_hook("offload_push_guard", payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"] if result.stdout.strip() else ""

    def state_file(self, session: str) -> Path:
        """Return the session's hook_state.json."""
        return self.directory / "state" / session / "hook_state.json"

    def test_prefix_sessions_each_nudge_once(self) -> None:
        """Sessions 'ab' and 'abc' both nudge once; 'ab' state never suppresses 'abc'."""
        self.assertTrue(self.offload("ab"))
        self.assertEqual(self.offload("ab"), "")
        self.assertTrue(self.offload("abc"))
        self.assertEqual(self.offload("abc"), "")
        self.assertEqual(json.loads(self.state_file("ab").read_text())["nudged"], {"offload_push_guard": True})
        self.assertEqual(json.loads(self.state_file("abc").read_text())["nudged"], {"offload_push_guard": True})
        counts = count_reasons(self.directory / "state")
        self.assertEqual((counts["nudge_first"], counts["nudge_suppressed"]), (2, 2))

    def test_payload_without_session_id_still_nudges_and_is_counted(self) -> None:
        """No session_id must not silently suppress the nudge; the unkeyed session is traced nudge_first."""
        transcript = self.directory / "t.jsonl"
        message = {"type": "assistant", "message": {"content": [{"type": "text", "text": OFFLOAD}]}}
        transcript.write_text(json.dumps(message) + "\n")
        result = self.run_hook("offload_push_guard", {"transcript_path": str(transcript), "hook_event_name": "Stop"})
        self.assertIn("offload-guard", result.stdout)
        self.assertEqual(count_reasons(self.directory / "state")["nudge_first"], 1)

    def test_no_go_block_is_counted(self) -> None:
        """The NO-GO verdict emitted by loop_state_guard (eval_verdict_no_go) has a live counter key."""
        with patch.dict(os.environ, self.environment):
            append_row("loop_state_guard", "blocked", "eval_verdict_no_go", "S1")
        counts = count_reasons(self.directory / "state")
        self.assertEqual(counts["eval_verdict_no_go"], 1)
        self.assertNotIn("eval_verdict_no-go", counts)

    def test_discipline_log_cannot_suppress_a_nudge(self) -> None:
        """A forged 'nudged=1' log line has no effect on the nudge decision."""
        (self.directory / "discipline.log").write_text("hook=offload_push_guard session=ab nudged=1\n")
        self.assertTrue(self.offload("ab"))

    def test_discipline_log_cannot_release_grace(self) -> None:
        """A forged absent-block log line leaves the first absent-state Stop blocked."""
        (self.directory / "discipline.log").write_text(
            "hook=loop_state_guard session=S1 invocations=1 reason=absent blocked=1\n"
        )
        payload = self.payload(self.transcript())
        self.assertEqual(self.run_hook("loop_state_guard", payload).returncode, 2)
        self.assertEqual(self.run_hook("loop_state_guard", payload).returncode, 0)  # the real record releases once

    def test_torn_state_does_not_release_grace_or_nudge(self) -> None:
        """A torn file blocks (grace) and suppresses (nudge); both are traced hook_state_unreadable."""
        self.state_file("S1").parent.mkdir(parents=True)
        self.state_file("S1").write_text("{torn")
        payload = self.payload(self.transcript())
        for _ in range(2):
            self.assertEqual(self.run_hook("loop_state_guard", payload).returncode, 2)
        self.state_file("ab").parent.mkdir(parents=True)
        self.state_file("ab").write_text("{torn")
        self.assertEqual(self.offload("ab"), "")
        counts = count_reasons(self.directory / "state")
        self.assertEqual((counts["hook_state_unreadable"], counts["nudge_first"]), (3, 0))

    def test_unsupported_schema_and_malformed_entries_are_unreadable(self) -> None:
        """Unknown versions and malformed nested fields cannot release grace or be overwritten."""
        state_file = self.state_file("S1")
        state_file.parent.mkdir(parents=True)
        invalid_states: list[dict[str, Any]] = [
            {"ordinals": {"absent_blocked": 1}, "arms": [], "nudged": {}},
            {"schema_version": 2, "ordinals": {"absent_blocked": 1}, "arms": [], "nudged": {}},
            {"schema_version": 1, "ordinals": {"absent_blocked": True}, "arms": [], "nudged": {}},
            {"schema_version": 1, "ordinals": {}, "arms": [{"hook": "loop_state_guard"}], "nudged": {}},
            {"schema_version": 1, "ordinals": {}, "arms": [], "nudged": {"offload_push_guard": 1}},
        ]
        for invalid in invalid_states:
            with self.subTest(invalid=invalid), patch.dict(os.environ, self.environment):
                state_file.write_text(json.dumps(invalid))
                before = state_file.read_bytes()
                self.assertIsNone(hook_state.load_state("S1", "loop_state_guard"))
                self.assertFalse(hook_state.mark_nudged("S1", "offload_push_guard"))
                self.assertEqual(state_file.read_bytes(), before)

    def test_ordinals_and_arms_persist(self) -> None:
        """record_absent_block stores the ordinal and appends an arms row each time; nudged is untouched."""
        with patch.dict(os.environ, self.environment):
            for ordinal in (1, 2):
                hook_state.record_absent_block(LoopState(self.directory / "p.json", "S1", ordinal, {}))
            self.assertTrue(hook_state.mark_nudged("S1", "unregistered_loop_guard"))
            self.assertFalse(hook_state.mark_nudged("S1", "unregistered_loop_guard"))
        state: dict[str, Any] = json.loads(self.state_file("S1").read_text())
        self.assertEqual(state["schema_version"], 1)
        self.assertEqual(state["ordinals"], {"absent_blocked": 2})
        self.assertEqual(
            state["arms"],
            [{"hook": "loop_state_guard", "ordinal": 1}, {"hook": "loop_state_guard", "ordinal": 2}],
        )
        self.assertEqual(state["nudged"], {"unregistered_loop_guard": True})

    def test_unsafe_session_ids_have_no_state_path(self) -> None:
        """An id that is not path-local gets no file (and so no grace, no dedupe) rather than a shared one."""
        for session in ("", "?", "a/b", "x..y"):
            self.assertIsNone(hook_state.state_path(session))


if __name__ == "__main__":
    unittest.main()
