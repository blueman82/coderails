"""A local request marker must survive before Coderails calls Muninn."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.lib import memory_request as mr
from scripts.lib import orders
from scripts.lib import orders_ledger as ol
from scripts.lib import orders_lifecycle as lifecycle
from scripts.lib import orders_request as request_sync
from scripts.tests.orders_recovery_test import RecoveryCase

RID = "R_" + "a" * 32
LESSON = "Check each request before you submit another one."
WINDOW = {
    "source": {"provider": "claude", "thread_id": "s1"},
    "from_line": 1,
    "through_line": 4,
    "boundary_hash": "a" * 64,
}
PENDING = mr.Pending(RID, WINDOW, "project-1")

TRANSITION_PROBE = r"""
import argparse, hashlib, json, socket, subprocess, sys
from pathlib import Path
from unittest import mock
sys.path.insert(0, sys.argv[1])
from scripts.lib import memory_adapter as ma, memory_request as mr, orders, orders_ledger as ol, orders_request as req
def blocked(*args, **kwargs):
    raise AssertionError('real subprocess/network/provider/Muninn launch forbidden')
subprocess.Popen = blocked
socket.socket = blocked
repo = Path(sys.argv[2]); repo.mkdir()
known = sys.argv[3] == 'known'
claim, task, session = 'Check the saved request.', 'loop-1', 's1'
rid = 'R_' + 'a' * 32
window = {'source': {'provider': 'claude', 'thread_id': session}, 'from_line': 1,
          'through_line': 4, 'boundary_hash': 'a' * 64}
field = {'state': 'pending' if known else 'unknown', 'id': None, 'request_id': rid if known else None,
         'task': task, 'source_session': session, 'claim_sha256': hashlib.sha256(claim.encode()).hexdigest(),
         'reason_code': 'learning_pending' if known else 'muninn_timeout'}
if known: field.update(request_window=window, project_id='project-1')
ledger = ol.record(ol.empty(), 'order-1', claim, session_id=session, loop_id=task,
                   now='2026-10-30T00:00:00+00:00')['ledger']
ol.save(repo/'orders.json', ol.set_muninn(ledger, 'order-1', field))
args = argparse.Namespace(order_id='order-1', session=session, quote='')
detail = {'request': {'id': rid, 'state': 'running', 'window': window,
                     'scope': {'project_id': 'project-1', 'task': task}}, 'receipt': None}
observations = []
with mock.patch.object(orders.dir_lock, 'process_start', return_value='private-test-process'), \
     mock.patch.object(req.lifecycle, 'check_staged_identity'), \
     mock.patch.object(mr, 'submit', return_value=mr.Pending(rid, window, 'project-1')) as submit, \
     mock.patch.object(ma, 'run_cli', return_value=json.dumps(detail)) as wire:
    for mode in ('muninn', 'off', 'muninn'):
        before = wire.call_count
        with mock.patch.object(ma, 'backend', return_value=mode):
            result, code = orders.cmd_cite(args, repo)
        current = ol.find(ol.open_ledger(repo), 'order-1')
        observations.append({'mode': mode, 'code': code, 'field': result['muninn'],
                             'submits': submit.call_count, 'wire_calls': wire.call_count - before,
                             'record_needs_submit': req.needs_submit(current, task, session)})
    print(json.dumps(observations))
    submit.assert_not_called()
    for observation in observations:
        assert not observation['record_needs_submit'], observation
        if observation['mode'] == 'off': assert observation['wire_calls'] == 0
        if not known:
            assert observation['field'] == field and observation['code'] == 3, observation
        else:
            assert observation['field']['request_id'] == rid
            assert observation['code'] == (0 if observation['mode'] == 'off' else 3)
    assert wire.call_args_list == ([mock.call(['learn', 'show', rid])] * 2 if known else [])
"""


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


class ClaimReadBoundary(RecoveryCase):
    """The same canonical lesson claim survives sync, completion and public reads."""

    def test_whitespace_lesson_survives_public_tick_and_query(self) -> None:
        """Normalize comparisons while preserving the authored source text."""
        raw = "  Use the checked\n  current result.  "
        claim = "Use the checked current result."
        for codex in (False, True):
            with self.subTest(codex=codex):
                self.configure(codex, "whitespace")
                self.owner("s1")
                args = (
                    "record",
                    "--id",
                    "order-1",
                    "--failure-mode",
                    "order-1",
                    "--lesson",
                    raw,
                    "--scope",
                    "agnostic",
                    "--loop",
                    "logical-s1",
                )
                code, pending = self.cli(*args)
                self.assertEqual(code, 3)
                self.assertEqual(
                    self.muninn(
                        "learn",
                        "complete",
                        pending["muninn"]["request_id"],
                        "--kind",
                        "lesson",
                        "--content",
                        claim,
                        extra_env=self.native_env,
                    )[0],
                    0,
                )
                code, synced = self.cli(*args)
                self.assertEqual((code, synced["muninn"]["state"]), (0, "written"))
                self.complete("s1")
                code, ticked = self.cli("tick", "--loop", "logical-s1")
                self.assertEqual(code, 0, ticked)
                code, queried = self.cli("query", script="lessons.py")
                self.assertEqual((code, queried["lessons"][0]["text"]), (0, claim))
                self.assertEqual(ol.open_ledger(self.repo)["orders"][0]["lesson"], raw)


class PublicRetryFence(unittest.TestCase):
    """The real cite/save flow preserves uncertainty and reuses known requests."""

    def test_off_on_keeps_unknown_fence_and_known_request_in_both_providers(self) -> None:
        """Fresh module namespaces exercise each independently installed provider layout."""
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory)
            for provider in (root, root / "packages/codex"):
                for state in ("unknown", "known"):
                    case = private / f"{provider.name}-{state}"
                    home = private / "home"
                    home.mkdir(exist_ok=True)
                    with self.subTest(provider=provider, state=state):
                        result = subprocess.run(
                            [sys.executable, "-c", TRANSITION_PROBE, str(provider), str(case), state],
                            cwd=private,
                            capture_output=True,
                            text=True,
                            check=False,
                            env={
                                **os.environ,
                                "HOME": str(home),
                                "XDG_CONFIG_HOME": str(home / "config"),
                                "XDG_DATA_HOME": str(home / "data"),
                                "MUNINN_HOME": str(home / "no-live-store"),
                            },
                        )
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
