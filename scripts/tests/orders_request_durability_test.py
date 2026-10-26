"""A local request marker must survive before Coderails calls Muninn."""

from __future__ import annotations

import argparse
import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.lib import memory_request as mr
from scripts.lib import orders
from scripts.lib import orders_ledger as ol
from scripts.lib import orders_lifecycle as lifecycle
from scripts.lib import orders_request as request_sync

RID = "R_" + "a" * 32
LESSON = "Check each request before you submit another one."
WINDOW = {
    "source": {"provider": "claude", "thread_id": "s1"},
    "from_line": 1,
    "through_line": 4,
    "boundary_hash": "a" * 64,
}
PENDING = mr.Pending(RID, WINDOW, "project-1")


class DurableRequestTests(unittest.TestCase):
    """Test the save boundary around one external submission."""

    def setUp(self) -> None:
        """Create a private order directory with no live Muninn access."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = Path(directory.name)
        self.state_dir = self.repo / "s1"
        self.state_dir.mkdir()
        self.binding = {"loop_id": "loop-1"}

    def record_args(self) -> argparse.Namespace:
        """Return one stable record command."""
        return argparse.Namespace(
            id="order-1",
            failure_mode="order-1",
            lesson=LESSON,
            scope="repo",
            session="s1",
            loop="loop-1",
            quote="",
        )

    def owner(self) -> contextlib.ExitStack:
        """Replace only graph ownership and observation, not local publication."""
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(orders, "locked", return_value=contextlib.nullcontext()))
        stack.enter_context(
            mock.patch.object(
                lifecycle,
                "owned",
                return_value=(
                    self.state_dir,
                    {"status": "in-progress"},
                    self.binding,
                ),
            )
        )
        stack.enter_context(mock.patch.object(lifecycle, "observe"))
        stack.enter_context(mock.patch.object(lifecycle, "check_staged_identity"))
        return stack

    def test_record_save_failure_does_not_submit(self) -> None:
        """A failed first marker save must leave Muninn untouched."""
        self.owner()
        with (
            mock.patch.object(orders, "_prepare", side_effect=OSError("injected")),
            mock.patch.object(mr, "submit", return_value=PENDING) as submit,
        ):
            payload, rc = orders.cmd_record(self.record_args(), self.repo)
        self.assertEqual((rc, payload["reason_code"]), (2, "order_state_error"))
        submit.assert_not_called()

    def test_record_second_save_failure_keeps_marker_and_does_not_resubmit(self) -> None:
        """A lost R_ reply leaves a durable unknown marker for the next attempt."""
        self.owner()
        real_prepare = orders._prepare  # pyright: ignore[reportPrivateUsage]
        calls = 0

        def fail_second(state_dir: Path, prepared: dict[str, object]) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected")
            real_prepare(state_dir, prepared)

        with (
            mock.patch.object(orders, "_prepare", side_effect=fail_second),
            mock.patch.object(mr, "submit", return_value=PENDING) as submit,
        ):
            self.assertEqual(orders.cmd_record(self.record_args(), self.repo)[1], 2)
        with mock.patch.object(mr, "inspect", return_value=PENDING):
            payload, rc = orders.cmd_record(self.record_args(), self.repo)
        self.assertEqual((rc, payload["muninn"]["state"], payload["muninn"]["request_id"]), (3, "pending", RID))
        submit.assert_called_once()

    def test_cite_save_failure_does_not_submit(self) -> None:
        """A cited order must save its marker before external submission."""
        self.owner()
        ledger = ol.record(
            ol.empty(),
            "order-1",
            LESSON,
            session_id="s1",
            loop_id="loop-1",
            now="2026-10-26T00:00:00+00:00",
            scope="repo",
        )["ledger"]
        ol.save(self.repo / "orders.json", ledger)
        args = argparse.Namespace(order_id="order-1", session="s1", quote="owner words")
        with (
            mock.patch.object(ol, "save", side_effect=OSError("injected")),
            mock.patch.object(mr, "submit", return_value=PENDING) as submit,
        ):
            payload, rc = orders.cmd_cite(args, self.repo)
        self.assertEqual((rc, payload["reason_code"]), (2, "order_state_error"))
        submit.assert_not_called()

    def test_old_quote_option_is_reported_ignored(self) -> None:
        """A caller sees that a quote does not enter Muninn's task request."""
        self.owner()
        args = self.record_args()
        args.quote = "Words typed by the owner."
        with mock.patch.object(mr, "submit", return_value=PENDING) as submit:
            payload, rc = orders.cmd_record(args, self.repo)
        self.assertEqual((rc, payload["quote_ignored"]), (3, True))
        submit.assert_called_once_with("s1", "loop-1")

    def test_cite_final_save_failure_recovers_exact_saved_request(self) -> None:
        """The reply journal preserves R_ when the last ledger save fails."""
        self.owner()
        ledger = ol.record(
            ol.empty(),
            "order-1",
            LESSON,
            session_id="s1",
            loop_id="loop-1",
            now="2026-10-26T00:00:00+00:00",
            scope="repo",
        )["ledger"]
        ol.save(self.repo / "orders.json", ledger)
        args = argparse.Namespace(order_id="order-1", session="s1", quote="")
        real_save = ol.save
        calls = 0

        def fail_final(path: Path, value: dict[str, object]) -> None:
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("injected")
            real_save(path, value)

        with (
            mock.patch.object(ol, "save", side_effect=fail_final),
            mock.patch.object(mr, "submit", return_value=PENDING) as submit,
        ):
            self.assertEqual(orders.cmd_cite(args, self.repo)[1], 2)
        with mock.patch.object(mr, "inspect", return_value=PENDING):
            payload, rc = orders.cmd_cite(args, self.repo)
        self.assertEqual((rc, payload["muninn"]["request_id"]), (3, RID))
        submit.assert_called_once()

    def test_journal_rejects_a_foreign_session(self) -> None:
        """A reply file for a different caller cannot restore this marker."""
        order = {"id": "order-1", "lesson": LESSON, "muninn": {"state": "unknown"}}
        field = {"request_id": RID, "request_window": WINDOW, "project_id": "project-1"}
        request_sync.save_response(order, self.repo, "s1", "loop-1", field)
        path = next(self.repo.glob("order-request-*.json"))
        row = json.loads(path.read_text())
        row["session"] = "other"
        path.write_text(json.dumps(row))
        with self.assertRaisesRegex(ValueError, "order_state_error"):
            request_sync.recover(order, self.repo, "s1", "loop-1")


if __name__ == "__main__":
    unittest.main()
