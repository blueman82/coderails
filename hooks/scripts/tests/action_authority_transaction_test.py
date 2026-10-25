#!/usr/bin/env python3
"""Receipt marker failures deny the action and keep batch accounting consistent."""

from __future__ import annotations

import contextlib
import fcntl
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts import action_authority_gate as gate  # noqa: E402
from hooks.scripts.tests.receipt_hook_case import MERGE, PUSH, ReceiptHookCase  # noqa: E402
from scripts.lib import merge_budget  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]


class TransactionGateTests(ReceiptHookCase):
    """Drive the real root hook and its receipt marker transaction."""

    def test_marker_write_error_denies_at_the_real_hook(self) -> None:
        """A failed receipt note cannot pass through the hook's fail-open exception handler."""
        self.configure("enforce")
        self.mint(MERGE, "merge")
        original = Path.write_text

        def write(path: Path, data: str, encoding: str | None = None, errors: str | None = None) -> int:
            if path.suffix == ".consumed":
                original(path, "", encoding=encoding, errors=errors)
                raise OSError("marker write failed")
            return original(path, data, encoding=encoding, errors=errors)

        output = io.StringIO()
        with (
            mock.patch.dict(os.environ, self.environment),
            mock.patch.object(gate, "read_payload_strict", return_value=self.payload(MERGE)),
            mock.patch.object(Path, "write_text", autospec=True, side_effect=write),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(gate.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("denied_marker_write_failed", self.reasons())
        self.assertFalse((self.loop / "s1/receipts/r1.consumed").exists())

    def test_advisory_rollback_error_denies_at_the_real_hook(self) -> None:
        """A failed reservation release cannot allow a later unbound merge."""
        self.configure("advisory")
        self.grant()
        output = io.StringIO()
        with (
            mock.patch.dict(os.environ, self.environment),
            mock.patch.object(
                gate, "read_payload_strict", return_value=self.payload(f"{MERGE} && gh pr merge 13 --squash")
            ),
            mock.patch.object(merge_budget, "settle", side_effect=OSError("unlink failed")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(gate.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertNotIn("action_authority_failed_open", self.reasons())

    def test_budget_unlock_error_denies_at_the_real_hook(self) -> None:
        """A lock teardown error cannot turn an enforce refusal into an allow."""
        self.configure("enforce")
        self.grant()
        original = fcntl.flock

        def flock(fd: int, operation: int) -> None:
            if operation == fcntl.LOCK_UN:
                raise OSError("unlock failed")
            original(fd, operation)

        output = io.StringIO()
        with (
            mock.patch.dict(os.environ, self.environment),
            mock.patch.object(gate, "read_payload_strict", return_value=self.payload("gh pr merge 12 --squash")),
            mock.patch.object(fcntl, "flock", side_effect=flock),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(gate.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertNotIn("action_authority_failed_open", self.reasons())

    def test_unexpected_error_uses_live_authority_error_policy(self) -> None:
        """Advisory warns without a grant, but a loaded grant or enforce mode denies."""
        for mode, live, denied in (("advisory", False, False), ("advisory", True, True), ("enforce", False, True)):
            with self.subTest(mode=mode, live=live):
                self.configure(mode)
                path = self.loop / "s1/authority.json"
                if live:
                    self.grant()
                else:
                    path.unlink(missing_ok=True)
                output = io.StringIO()
                with (
                    mock.patch.dict(os.environ, self.environment),
                    mock.patch.object(gate, "read_payload_strict", return_value=self.payload(MERGE)),
                    mock.patch.object(gate, "check_and_consume", side_effect=RuntimeError("unexpected")),
                    contextlib.redirect_stdout(output),
                ):
                    self.assertEqual(gate.main(), 0)
                self.assertEqual(bool(output.getvalue()), denied)
                self.assertEqual(self.reasons()[-1], "denied_gate_error" if denied else "action_authority_failed_open")

    def test_trace_failure_cannot_remove_enforce_denial(self) -> None:
        """The hook emits a deny envelope even when its audit row cannot be written."""
        self.configure("enforce")
        output = io.StringIO()
        with (
            mock.patch.dict(os.environ, self.environment),
            mock.patch.object(gate, "read_payload_strict", return_value=self.payload(MERGE)),
            mock.patch.object(gate, "check_and_consume", side_effect=RuntimeError("unexpected")),
            mock.patch.object(gate, "append_row", side_effect=OSError("trace failed")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(gate.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_failed_rollback_keeps_receipt_spent_and_denies(self) -> None:
        """A marker that cannot be removed stays spent while the guarded command is denied."""
        self.configure("enforce")
        self.mint(MERGE, "merge")
        original_write = Path.write_text
        original_unlink = Path.unlink

        def write(path: Path, data: str, encoding: str | None = None, errors: str | None = None) -> int:
            if path.suffix == ".consumed":
                raise OSError("write failed")
            return original_write(path, data, encoding=encoding, errors=errors)

        def unlink(path: Path, missing_ok: bool = False) -> None:
            if path.suffix == ".consumed":
                raise OSError("unlink failed")
            return original_unlink(path, missing_ok=missing_ok)

        output = io.StringIO()
        with (
            mock.patch.dict(os.environ, self.environment),
            mock.patch.object(gate, "read_payload_strict", return_value=self.payload(MERGE)),
            mock.patch.object(Path, "write_text", autospec=True, side_effect=write),
            mock.patch.object(Path, "unlink", autospec=True, side_effect=unlink),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(gate.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("denied_marker_cleanup_failed", self.reasons())
        self.assertTrue((self.loop / "s1/receipts/r1.consumed").exists())

    def test_waiting_hook_can_claim_after_failed_batch_rolls_back(self) -> None:
        """A waiting hook sees the receipt only after the first batch rolls back under the lock."""
        self.configure("enforce")
        self.mint(PUSH, "git_push")
        entered = self.directory / "entered"
        release = self.directory / "release"
        failing = """
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from hooks.scripts import action_authority_gate as gate
entered, release = Path(sys.argv[2]), Path(sys.argv[3])
original = Path.write_text
def write(path, data, *args, **kwargs):
    if path.suffix == '.consumed':
        entered.touch()
        deadline = time.monotonic() + 10
        while not release.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        raise OSError('record failed')
    return original(path, data, *args, **kwargs)
Path.write_text = write
raise SystemExit(gate.main())
"""
        first = subprocess.Popen(
            [sys.executable, "-c", failing, str(ROOT), str(entered), str(release)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            env=self.environment,
        )
        assert first.stdin is not None and first.stdout is not None
        first.stdin.write(json.dumps(self.payload(PUSH)))
        first.stdin.close()
        deadline = time.monotonic() + 10
        while not entered.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(entered.exists(), "first hook never reached marker recording")
        second = subprocess.Popen(
            [sys.executable, str(ROOT / "hooks/scripts/action_authority_gate.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            env=self.environment,
        )
        release.touch()
        second_out, _ = second.communicate(json.dumps(self.payload(PUSH)), timeout=15)
        first_out = first.stdout.read()
        first.stdout.close()
        self.assertEqual(first.wait(timeout=15), 0)
        self.assertEqual(second.returncode, 0)
        self.assertIn('"permissionDecision": "deny"', first_out)
        self.assertNotIn('"permissionDecision": "deny"', second_out)
        self.assertEqual(self.reasons().count("receipt_consumed"), 1)
