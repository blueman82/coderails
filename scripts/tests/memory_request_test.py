"""A Muninn review request never counts as a written note."""

# ruff: noqa: D101, D102

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.lib import decision_record as decisions  # noqa: E402
from scripts.lib import memory_adapter as ma  # noqa: E402
from scripts.lib import memory_request as mr  # noqa: E402
from scripts.lib import orders_lifecycle as lifecycle  # noqa: E402
from scripts.lib import orders_request as request_sync  # noqa: E402

RID = "R_" + "a" * 32
KID = "K_" + "b" * 32
PROJECT = "coderails-project"
SCOPE = {"project_id": PROJECT, "task": "loop-1"}
WINDOW = {
    "source": {"provider": "codex", "thread_id": "session-1"},
    "from_line": 1,
    "through_line": 4,
    "boundary_hash": "a" * 64,
}
CLAIM = "2.5: Use the current request API."


class RequestTest(unittest.TestCase):
    def test_submit_is_pending_and_task_bound(self) -> None:
        with (
            mock.patch.object(mr, "probe", return_value=None),
            mock.patch.object(
                ma, "_run", return_value=json.dumps({"id": RID, "scope": SCOPE, "window": WINDOW})
            ) as run,
        ):
            self.assertEqual(mr.submit("session-1", "loop-1"), mr.Pending(RID, WINDOW, PROJECT))
        run.assert_called_once_with(["learn", "request", "--session", "session-1", "--task", "loop-1"])

    def test_pending_receipt_is_never_written(self) -> None:
        detail = {"request": {"id": RID, "scope": SCOPE, "window": WINDOW, "state": "running"}, "receipt": None}
        with mock.patch.object(ma, "_run", return_value=json.dumps(detail)) as run:
            self.assertEqual(mr.inspect(RID, "loop-1", "decision", CLAIM), mr.Pending(RID, WINDOW, PROJECT))
        run.assert_called_once_with(["learn", "show", RID])

    def test_recovered_request_rejects_a_changed_source_window(self) -> None:
        detail = {
            "request": {"id": RID, "scope": SCOPE, "window": {**WINDOW, "through_line": 5}, "state": "running"},
            "receipt": None,
        }
        with mock.patch.object(ma, "_run", return_value=json.dumps(detail)):
            self.assertEqual(
                mr.inspect(RID, "loop-1", "decision", CLAIM, expected_window=WINDOW, expected_project=PROJECT),
                ma.Degraded("muninn_bad_output"),
            )

    def test_completed_receipt_needs_exact_current_note(self) -> None:
        detail = {
            "request": {"id": RID, "scope": SCOPE, "state": "completed"},
            "receipt": {"request_id": RID, "applied": [{"knowledge_id": KID, "revision": 1}]},
        }
        listed = {"knowledge": [{"id": KID, "revision": 1}]}
        shown = {
            "id": KID,
            "revision": 1,
            "state": "active",
            "body": {
                "form": "note",
                "kind": "decision",
                "content": CLAIM,
                "scope": SCOPE,
            },
            "evidence_sources": [{"ref": "codex:session-1:3.1"}],
        }
        with mock.patch.object(ma, "_run", side_effect=map(json.dumps, (detail, listed, shown))):
            result = mr.inspect(RID, "loop-1", "decision", CLAIM)
        self.assertIsInstance(result, ma.Record)
        assert isinstance(result, ma.Record)
        self.assertEqual(result.id, KID)

    def test_project_note_returned_by_task_list_is_not_exact_task(self) -> None:
        detail: dict[str, Any] = {
            "request": {"id": RID, "scope": SCOPE, "state": "completed"},
            "receipt": {"request_id": RID, "applied": [{"knowledge_id": KID, "revision": 1}]},
        }
        listed = {"knowledge": [{"id": KID, "revision": 1}]}
        shown = {
            "id": KID,
            "revision": 1,
            "state": "active",
            "body": {
                "form": "note",
                "kind": "decision",
                "content": CLAIM,
                "scope": {"project_id": PROJECT, "task": None},
            },
            "evidence_sources": [{"ref": "codex:session-1:3.1"}],
        }
        with mock.patch.object(ma, "_run", side_effect=map(json.dumps, (detail, listed, shown))):
            self.assertEqual(mr.inspect(RID, "loop-1", "decision", CLAIM), ma.Degraded("learning_no_matching_record"))

    def test_no_change_receipt_is_not_written(self) -> None:
        detail: dict[str, Any] = {
            "request": {"id": RID, "scope": SCOPE, "state": "completed"},
            "receipt": {"request_id": RID, "applied": []},
        }
        listed: dict[str, Any] = {"knowledge": []}
        with mock.patch.object(ma, "_run", side_effect=map(json.dumps, (detail, listed))):
            self.assertEqual(mr.inspect(RID, "loop-1", "decision", CLAIM), ma.Degraded("learning_no_matching_record"))

    def test_decision_without_saved_window_stays_unknown(self) -> None:
        row = {
            "phase": "2.5",
            "decision": "Use the current request API.",
            "muninn": {"request_id": RID, "state": "pending"},
        }
        with (
            mock.patch.object(mr, "submit") as submit,
            mock.patch.object(mr, "inspect") as inspect,
        ):
            field = decisions.sync_row(row, "loop-1", "session-1", "")
        self.assertEqual(field["state"], "unknown")
        self.assertEqual(field["request_id"], RID)
        submit.assert_not_called()
        inspect.assert_not_called()

    def test_decision_keeps_source_window_for_saved_request(self) -> None:
        row = {
            "phase": "2.5",
            "decision": "Use the current request API.",
            "muninn": {"request_id": RID, "state": "pending", "request_window": WINDOW, "project_id": PROJECT},
        }
        with mock.patch.object(mr, "inspect", return_value=mr.Pending(RID, WINDOW, PROJECT)) as inspect:
            field = decisions.sync_row(row, "loop-1", "session-1", "")
        inspect.assert_called_once_with(
            RID, "loop-1", "decision", CLAIM, expected_window=WINDOW, expected_project=PROJECT
        )
        self.assertEqual((field["request_window"], field["project_id"]), (WINDOW, PROJECT))

    def test_ambiguous_decision_submit_stays_unknown(self) -> None:
        row = {"phase": "2.5", "decision": "Use the current request API.", "muninn": {"state": "syncing"}}
        with mock.patch.object(mr, "submit", return_value=ma.Degraded("muninn_timeout")):
            field = decisions.sync_row(row, "loop-1", "session-1", "")
        self.assertEqual((field["state"], field["reason_code"]), ("unknown", "muninn_timeout"))

    def test_order_unknown_does_not_submit_again(self) -> None:
        claim = "Run a bounded review before closing the loop."
        previous = {
            "state": "unknown",
            "id": None,
            "request_id": None,
            "claim_sha256": hashlib.sha256(claim.encode()).hexdigest(),
            "reason_code": "muninn_timeout",
        }
        order = {"id": "order-1", "lesson": claim, "muninn": previous}
        with mock.patch.object(lifecycle, "check_staged_identity"), mock.patch.object(mr, "submit") as submit:
            field = request_sync.sync_order(order, "session-1", Path("/tmp"), {}, "loop-1")
        self.assertEqual(field, previous)
        submit.assert_not_called()

    def test_same_text_in_a_later_task_needs_its_own_request(self) -> None:
        claim = "Run a bounded review before closing the loop."
        previous = {
            "state": "written",
            "id": KID,
            "request_id": RID,
            "task": "loop-1",
            "claim_sha256": hashlib.sha256(claim.encode()).hexdigest(),
            "reason_code": "ok",
        }
        order = {"id": "order-1", "lesson": claim, "muninn": previous}
        self.assertTrue(request_sync.needs_submit(order, "loop-2", "session-2"))
        with mock.patch.object(lifecycle, "check_staged_identity"):
            marker = request_sync.sync_order(order, "session-2", Path("/tmp"), {}, "loop-2")
        self.assertEqual((marker["state"], marker["task"], marker["request_id"]), ("unknown", "loop-2", None))

    def test_same_text_from_another_session_needs_its_own_request(self) -> None:
        claim = "Run a bounded review before closing the loop."
        previous = {
            "state": "pending",
            "request_id": RID,
            "task": "loop-1",
            "source_session": "session-1",
            "claim_sha256": hashlib.sha256(claim.encode()).hexdigest(),
        }
        order = {"id": "order-1", "lesson": claim, "muninn": previous}
        self.assertTrue(request_sync.needs_submit(order, "loop-1", "session-2"))
        with mock.patch.object(lifecycle, "check_staged_identity"):
            marker = request_sync.sync_order(order, "session-2", Path("/tmp"), {}, "loop-1")
        self.assertEqual(
            (marker["state"], marker["source_session"], marker["request_id"]), ("unknown", "session-2", None)
        )

    def test_order_without_saved_window_stays_unknown(self) -> None:
        claim = "Run a bounded review before closing the loop."
        previous = {
            "state": "pending",
            "request_id": RID,
            "task": "loop-1",
            "source_session": "session-1",
            "claim_sha256": hashlib.sha256(claim.encode()).hexdigest(),
        }
        order = {"id": "order-1", "lesson": claim, "muninn": previous}
        with (
            mock.patch.object(lifecycle, "check_staged_identity"),
            mock.patch.object(mr, "inspect") as inspect,
            mock.patch.object(mr, "submit") as submit,
        ):
            field = request_sync.sync_order(order, "session-1", Path("/tmp"), {}, "loop-1")
        self.assertEqual((field["state"], field["request_id"]), ("unknown", RID))
        inspect.assert_not_called()
        submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
