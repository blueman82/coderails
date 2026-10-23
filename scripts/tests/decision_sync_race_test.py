"""A decision sync cannot be replayed while an external write is in flight or uncertain."""

from __future__ import annotations

import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from hooks.scripts.lib.graph_executor import transition as claude_transition
from hooks.scripts.tests.lib import claude_transcript_fixture as fixture
from scripts.lib import decision_record as dr
from scripts.lib import memory_adapter as ma
from scripts.tests.decision_record_test import Base

WRITTEN = {"state": "written", "id": "K1", "reason_code": "ok"}


class SyncRaceTests(Base):
    """Use the real graph lock and a controlled fake external write."""

    def test_flush_cannot_duplicate_an_inflight_record(self) -> None:
        """A second caller sees in-flight state and never calls Muninn."""
        entered = threading.Event()
        release = threading.Event()
        calls = 0
        result: list[dict[str, Any]] = []

        def blocked(*_args: object, **_kwargs: object) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                release.wait(5)
            return dict(WRITTEN)

        with mock.patch.object(dr, "sync_row", side_effect=blocked):
            worker = threading.Thread(target=lambda: result.append(self.rec()))
            worker.start()
            self.assertTrue(entered.wait(5))
            try:
                pending = dr.flush_pending(self.path, "s1", transition=claude_transition)
                self.assertEqual((pending["exit_code"], pending["reason_code"]), (3, "decision_sync_unknown"))
                self.assertEqual(calls, 1)
            finally:
                release.set()
                worker.join(5)
        self.assertEqual(result[0]["muninn"]["state"], "written")
        self.assertEqual(calls, 1)

    def test_crash_after_external_acceptance_is_not_retried(self) -> None:
        """A crash before the local confirmation leaves an explicit unknown, with no second write."""
        calls = 0

        def crash_after_append(path: Path, fn: Any) -> dict[str, Any]:  # noqa: ANN401
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("process died before local mark")
            return claude_transition(path, fn)

        with mock.patch.object(dr, "sync_row", return_value=dict(WRITTEN)) as sync:
            with self.assertRaises(RuntimeError):
                dr.record(self.path, "s1", "2.5", "adopt shape A", transition=crash_after_append)
            self.assertEqual(self.decisions()[0]["muninn"]["state"], "syncing")
            out = dr.flush_pending(self.path, "s1", transition=claude_transition)
            self.assertEqual((out["exit_code"], out["reason_code"]), (3, "decision_sync_unknown"))
            self.assertEqual(sync.call_count, 1)

    def test_ambiguous_external_result_needs_reconciliation(self) -> None:
        """A missing K-id after an attempted add cannot be assumed safe to retry."""
        with mock.patch.object(ma, "add", return_value=ma.Degraded("muninn_bad_output")) as add:
            out = self.rec()
            self.assertEqual((out["exit_code"], out["muninn"]["state"]), (3, "unknown"))
            retry = dr.flush_pending(self.path, "s1", transition=claude_transition)
            self.assertEqual((retry["exit_code"], retry["reason_code"]), (3, "decision_sync_unknown"))
            self.assertEqual(add.call_count, 1)

    def test_rearmed_loop_cannot_receive_old_sync_result(self) -> None:
        """An old result must not mark a replacement loop's first row."""
        entered = threading.Event()
        release = threading.Event()
        result: list[dict[str, Any]] = []

        def blocked(*_args: object, **_kwargs: object) -> dict[str, Any]:
            entered.set()
            release.wait(5)
            return dict(WRITTEN)

        with mock.patch.object(dr, "sync_row", side_effect=blocked):
            worker = threading.Thread(target=lambda: result.append(self.rec()))
            worker.start()
            self.assertTrue(entered.wait(5))
            try:
                fresh = {**fixture.state(), "session_id": "s1", "loop_id": "L2", "authorising_prompt_raw": "new prompt"}
                claude_transition(self.path, lambda _old: dr.add_decision(fresh, "s1", "2.5", "new choice")["state"])
            finally:
                release.set()
                worker.join(5)
        self.assertEqual(self.state()["loop_id"], "L2")
        self.assertEqual(self.decisions()[0]["muninn"]["state"], "syncing")
        self.assertEqual(result[0]["reason_code"], "decision_sync_unknown")

    def test_rearmed_loop_cannot_be_claimed_from_stale_flush_snapshot(self) -> None:
        """A stale flush snapshot must not claim a replacement loop's first row."""
        self.rec()
        old = self.state()
        old["decisions_absorbed"][0]["muninn"] = {"state": "degraded"}
        self.put(old)
        calls = 0

        def rearm_before_claim(path: Path, fn: Any) -> dict[str, Any]:  # noqa: ANN401
            nonlocal calls
            calls += 1
            if calls == 2:
                fresh = {**fixture.state(), "session_id": "s1", "loop_id": "L2", "authorising_prompt_raw": "new prompt"}

                def replace(_old: dict[str, Any]) -> dict[str, Any]:
                    new = dr.add_decision(fresh, "s1", "2.5", "new choice")["state"]
                    new["decisions_absorbed"][0]["muninn"] = {"state": "degraded"}
                    return new  # type: ignore[no-any-return]

                claude_transition(path, replace)
            return claude_transition(path, fn)

        with mock.patch.object(dr, "sync_row") as sync:
            out = dr.flush_pending(self.path, "s1", transition=rearm_before_claim)
        self.assertEqual((out["exit_code"], out["reason_code"]), (3, "decision_sync_unknown"))
        self.assertEqual(self.state()["loop_id"], "L2")
        self.assertEqual(self.decisions()[0]["muninn"]["state"], "degraded")
        sync.assert_not_called()


if __name__ == "__main__":
    unittest.main()
