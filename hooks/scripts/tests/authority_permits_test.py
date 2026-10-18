#!/usr/bin/env python3
"""Pin authority_permits.permits(): denied, approval_required_for, executed-marker max_prs, no-authority default."""

from __future__ import annotations

import filecmp
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib import action_receipt as ar
from scripts.lib import authority_permits as ap
from scripts.lib.authority_object import authority_path, read_authority, write_authority

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime.now(timezone.utc)


def authority(**over: object) -> dict[str, Any]:
    """A valid live authority object for session s1."""
    obj: dict[str, Any] = {
        "authority_id": "auth-1", "loop_id": None, "session_id": "s1", "scope": ["code"], "denied": [],
        "max_prs": 2, "expires_at": (NOW + timedelta(hours=1)).isoformat(), "revocable": True,
        "approval_required_for": ["merge"], "granted_by": "command",
    }  # fmt: skip
    return obj | over


class PermitsTests(unittest.TestCase):
    """Each rule of the permits() contract, against a temp loop dir."""

    def setUp(self) -> None:
        """Private loop dir passed as base."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)

    def grant(self, **over: object) -> None:
        """Write the session authority."""
        path = authority_path("s1", self.base)
        assert path is not None and write_authority(path, authority(**over))

    def execute(
        self, receipt_id: str, authority_id: str = "auth-1", action: str = "merge", marker: str = ".executed"
    ) -> None:
        """A receipt file plus one marker, as merge.py leaves it."""
        path = ar.receipt_path("s1", receipt_id, self.base)
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"receipt_id": receipt_id, "authority_id": authority_id, "action": action}))
        path.with_suffix(marker).write_text("")

    def permits(self, action: str) -> dict[str, Any]:
        """Call permits against the temp base."""
        return ap.permits("s1", action, NOW, self.base)

    def test_no_authority_allows_but_needs_a_receipt_for_merge_and_push(self) -> None:
        """Without crack-on a signed receipt is still required for merge and push to main."""
        for action, needs in (("merge", True), ("push_main", True), ("git_push", True), ("destructive_shell", False)):
            self.assertEqual(
                self.permits(action),
                {"allow": True, "reason": "no_authority", "requires_approval": needs, "authority_id": None},
            )

    def test_denied_category_blocks(self) -> None:
        """A live authority whose denied list names the category refuses it, and only it."""
        self.grant(denied=["merge", "destructive_shell"])
        merge = self.permits("merge")
        self.assertEqual((merge["allow"], merge["reason"]), (False, "authority_denied"))
        self.assertEqual(merge["authority_id"], "auth-1")
        self.assertFalse(self.permits("destructive_shell")["allow"])
        self.assertTrue(self.permits("push_main")["allow"])

    def test_approval_required_for_defaults_and_extras(self) -> None:
        """Merge always and push_main by default need approval; extras from the object add to that."""
        self.grant(approval_required_for=["merge", "deploy"])
        self.assertTrue(self.permits("merge")["requires_approval"])
        self.assertTrue(self.permits("push_main")["requires_approval"])
        self.assertTrue(self.permits("deploy")["requires_approval"])
        self.assertFalse(self.permits("destructive_shell")["requires_approval"])

    def test_max_prs_counts_only_executed_merges_for_this_authority(self) -> None:
        """Only executed merge receipts carrying this authority id spend its budget; pushes do not."""
        self.grant(max_prs=2)
        self.execute("r3", action="git_push")
        self.execute("r1", authority_id=None)  # type: ignore[arg-type]
        self.execute("r2", authority_id="other")
        self.assertTrue(self.permits("merge")["allow"])
        self.execute("r3", authority_id="auth-1")
        self.execute("r4", authority_id="auth-1")
        refused = self.permits("merge")
        self.assertEqual((refused["allow"], refused["reason"]), (False, "max_prs_exceeded"))
        self.assertTrue(self.permits("push_main")["allow"])

    def test_max_prs_zero_means_no_merge_under_the_authority(self) -> None:
        """The grant default of 0 permits no merge at all."""
        self.grant(max_prs=0)
        self.assertEqual(self.permits("merge")["reason"], "max_prs_exceeded")

    def test_consumed_but_not_executed_does_not_count(self) -> None:
        """A hook-consumed receipt that never reached gh does not spend the budget (the test pins executed)."""
        self.grant(max_prs=1)
        self.execute("r1", marker=".consumed")
        self.assertTrue(self.permits("merge")["allow"])

    def test_expired_authority_is_no_authority(self) -> None:
        """An expired object grants and denies nothing."""
        self.grant(denied=["merge"], expires_at=(NOW - timedelta(minutes=1)).isoformat())
        self.assertEqual(self.permits("merge")["reason"], "no_authority")

    def test_gate_summary_adds_up_hook_enforce_pr_workflow_and_merge_script(self) -> None:
        """gate_summary strips denied_/advisory_/merge_py_ so every caller lands in one counter."""
        from scripts.lib.receipt_counters import gate_summary

        aa = "action_authority"
        got = gate_summary({
            f"{aa}/denied/denied_authority_denied": 2, f"{aa}/denied/merge_py_authority_denied": 1,
            f"{aa}/denied/approval_requirement_missing": 1,
            f"{aa}/denied/denied_max_prs_exceeded": 1, f"{aa}/advisory/action_authority_bad_mode": 3,
            f"{aa}/denied/authority_denied_destructive_shell": 1, f"{aa}/denied/merge_py_no_receipt": 4,
            f"{aa}/allowed/merge_py_receipt_executed": 5, "capability/denied/authority_denied": 9,
        })  # fmt: skip
        self.assertEqual(got, {
            "authority_denied": 3, "approval_requirement_missing": 1, "max_prs_exceeded": 1,
            "action_authority_bad_mode": 3,
            "authority_denied_destructive_shell": 1, "no_receipt": 4, "merge_py_receipt_executed": 5,
        })  # fmt: skip

    def test_counters_cli_prints_the_gate_object(self) -> None:
        """The documented pipeline reaches gate_summary: stdin from measure_graph_alignment, `gate` in the output."""
        rows = {"trace": {"by_reason": {"action_authority/denied/denied_max_prs_exceeded": 2}}}
        done = subprocess.run(
            [sys.executable, str(ROOT / "scripts/lib/receipt_counters.py")], input=json.dumps(rows),
            capture_output=True, text=True, check=True,
        )  # fmt: skip
        self.assertEqual(json.loads(done.stdout)["gate"]["max_prs_exceeded"], 2)

    def test_deeply_nested_json_is_malformed_not_a_crash(self) -> None:
        """'[' * 7000 raises RecursionError in json.loads; it must read as none/malformed, never escape (fail-open)."""
        poison = "[" * 7000
        path = authority_path("s1", self.base)
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(poison)
        self.assertIsNone(read_authority("s1", self.base, NOW))
        receipt = path.parent / "receipts" / "0.json"
        receipt.parent.mkdir()
        receipt.write_text(poison)
        self.assertIsNone(ar.read_receipt(receipt))
        self.assertEqual(self.permits("merge")["reason"], "no_authority")

    def test_mirror_is_byte_identical(self) -> None:
        """The Codex copy is the Claude file."""
        for name in ("authority_permits.py", "receipt_gate.py", "action_receipt.py", "authority_object.py"):
            self.assertTrue(
                filecmp.cmp(ROOT / "scripts/lib" / name, ROOT / "packages/codex/scripts/lib" / name, shallow=False)
            )

    def test_files_stay_under_their_budgets(self) -> None:
        """authority_permits <=150 lines, receipt_gate <=200."""
        for name, limit in (("authority_permits.py", 150), ("receipt_gate.py", 200)):
            self.assertLessEqual(len((ROOT / "scripts/lib" / name).read_text().splitlines()), limit)


if __name__ == "__main__":
    unittest.main()
