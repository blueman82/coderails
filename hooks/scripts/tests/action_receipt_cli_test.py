#!/usr/bin/env python3
"""Pin the action-receipt CLI: round trip, revoke then verify, foreign-session refusal, trace reason codes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib import action_receipt as ar

REPO = Path(__file__).resolve().parents[3]
CLI = REPO / "scripts" / "action_receipt_cli.py"
COMMAND = "gh pr merge 12 --squash"


class CliTests(unittest.TestCase):
    """The CLI mints, inspects and revokes against an isolated loop dir."""

    def setUp(self) -> None:
        """Isolated loop dir."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.env = {**os.environ, "CLAUDE_AGENTIC_LOOP_DIR": self.tmp.name}

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run the CLI in the isolated env."""
        return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, env=self.env)

    def approve(self, session: str = "s1", command: str = COMMAND) -> dict[str, object]:
        """Mint a merge receipt and return it."""
        result = self.run_cli(
            "approve-action", "--session", session, "--loop", "L1", "--kind", "merge",
            "--command", command, "--cwd", "/repo", "--branch", "feature/x",
        )  # fmt: skip
        self.assertEqual(result.returncode, 0, result.stderr)
        minted: dict[str, object] = json.loads(result.stdout)
        return minted

    def reasons(self, session: str = "s1") -> list[str]:
        """Reason codes traced for a session."""
        path = self.base / session / "trace.jsonl"
        return [json.loads(line)["reason_code"] for line in path.read_text().splitlines()] if path.exists() else []

    def test_round_trip_matches_the_hook_view(self) -> None:
        """A minted receipt verifies against the action the hook would compute, and not against other args."""
        rec = self.approve()
        now = datetime.now(timezone.utc)
        same = ar.proposed_action("merge", COMMAND, "/repo", "feature/x")
        other = ar.proposed_action("merge", "gh pr merge 13 --squash", "/repo", "feature/x")
        self.assertEqual(ar.find_valid("s1", same, now, "L1", self.base), (rec, "ok"))
        self.assertEqual(ar.find_valid("s1", other, now, "L1", self.base), (None, "hash_mismatch"))
        self.assertEqual(self.reasons(), ["receipt_approved"])

    def test_size_limits_refused_with_reason_codes(self) -> None:
        """An oversized scope and a receipt beyond the per-session cap are refused and traced."""
        args = ("approve-action", "--session", "s1", "--kind", "merge", "--command", COMMAND, "--cwd", "/repo",
                "--branch", "feature/x")  # fmt: skip
        result = self.run_cli(*args, "--scope", "x" * 5000)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.reasons(), ["receipt_refused_scope_too_long"])
        for _ in range(ar.MAX_RECEIPTS):
            self.assertEqual(self.run_cli(*args).returncode, 0)
        self.assertEqual(self.run_cli(*args).returncode, 2)
        self.assertEqual(self.reasons()[-1], "receipt_refused_too_many")

    def test_oversized_receipt_file_is_malformed(self) -> None:
        """A hand-written huge receipt is never parsed."""
        path = ar.receipt_path("s1", "big", self.base)
        assert path is not None
        path.parent.mkdir(parents=True)
        path.write_text('{"scope": "' + "x" * (ar.MAX_RECEIPT_BYTES + 1) + '"}')
        self.assertIsNone(ar.read_receipt(path))

    def test_inspect_then_revoke_then_refused(self) -> None:
        """Revoke leaves the receipt inspectable, verification then says revoked, and a second revoke is refused."""
        rid = str(self.approve()["receipt_id"])
        shown = json.loads(self.run_cli("inspect-receipt", "--session", "s1", "--receipt-id", rid).stdout)
        self.assertFalse(shown["consumed"])
        self.assertEqual(self.run_cli("revoke-receipt", "--session", "s1", "--receipt-id", rid).returncode, 0)
        same = ar.proposed_action("merge", COMMAND, "/repo", "feature/x")
        self.assertEqual(ar.find_valid("s1", same, datetime.now(timezone.utc), "L1", self.base), (None, "revoked"))
        again = self.run_cli("revoke-receipt", "--session", "s1", "--receipt-id", rid)
        self.assertEqual(again.returncode, 2)
        self.assertIn("receipt_refused_already_revoked", self.reasons())

    def test_inspect_foreign_session_receipt_refused(self) -> None:
        """A receipt copied into another session's dir is refused, never shown."""
        rid = str(self.approve()["receipt_id"])
        foreign = self.base / "s2" / "receipts"
        foreign.mkdir(parents=True)
        (foreign / f"{rid}.json").write_text((self.base / "s1" / "receipts" / f"{rid}.json").read_text())
        result = self.run_cli("inspect-receipt", "--session", "s2", "--receipt-id", rid)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(rid, result.stdout)
        self.assertIn("receipt_refused_foreign_session", self.reasons("s2"))

    def test_missing_and_unsafe_ids_refused(self) -> None:
        """Unknown ids and path-unsafe ids are refused with stable codes."""
        self.assertEqual(self.run_cli("inspect-receipt", "--session", "s1", "--receipt-id", "nope").returncode, 2)
        self.assertIn("receipt_refused_missing", self.reasons())
        bad = self.run_cli("inspect-receipt", "--session", "../x", "--receipt-id", "r")
        self.assertEqual(bad.returncode, 2)
        self.assertIn("receipt_refused_unsafe_id", bad.stderr)


if __name__ == "__main__":
    unittest.main()
