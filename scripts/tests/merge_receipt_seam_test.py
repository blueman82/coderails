"""The merge command and receipt gate share one enforced authority seam."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import unittest
from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
_loaded = set(sys.modules)
from scripts import merge  # noqa: E402
from scripts.lib import action_receipt as receipt  # noqa: E402
from scripts.lib import git_common as git  # noqa: E402
from scripts.lib import manifest_policy, merge_budget, receipt_gate  # noqa: E402

for _name in set(sys.modules) - _loaded:
    if _name.startswith("scripts."):
        sys.modules.pop(_name)
        _parent, _, _leaf = _name.rpartition(".")
        if _parent in sys.modules:
            vars(sys.modules[_parent]).pop(_leaf, None)

SHA = "f" * 40
DENIED = {"allow": False, "reason": "authority_denied"}


class SeamSpyTests(unittest.TestCase):
    """merge.py reaches authority_permits.permits through the shared gate, and calls the gate exactly once."""

    def test_default_mode_does_not_require_a_merge_passphrase(self) -> None:
        """With no config, the direct merge path reports a missing receipt but proceeds."""
        with (
            mock.patch.object(receipt_gate, "_claim_merge", return_value="no_receipt"),
            mock.patch.object(receipt_gate, "append_row") as trace,
        ):
            receipt_gate.require_merge_receipt("7", "/nowhere")
        self.assertEqual(trace.call_args.args[1:3], ("advisory", "merge_py_no_receipt"))

    def test_merge_main_calls_the_seam_once_before_gh_pr_merge(self) -> None:
        """The order is: seam, then gh pr merge; a refusal from the seam stops before gh."""
        order: list[str] = []
        fields: dict[str, str] = {"state": "OPEN", "headRefOid": SHA, "title": "t", "headRefName": "feature"}

        def run(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
            del check
            order.append("gh" if args[:3] == ("gh", "pr", "merge") else "other")
            return subprocess.CompletedProcess(args, 0, "", "")

        def field(number: str, name: str, fallback: str = "") -> str:
            del number
            return fields.get(name, fallback)

        def seam_call(number: str, *, target: str, verified_sha: str) -> None:
            del number
            self.assertEqual((target, verified_sha), ("7", SHA))
            order.append("seam")

        with (
            mock.patch.object(git, "require_repo"), mock.patch.object(git, "main", return_value="main"),
            mock.patch.object(git, "protected", return_value=False), mock.patch.object(git, "run", side_effect=run),
            mock.patch.object(git, "pr_field", side_effect=field),
            mock.patch.object(merge, "verify_gates", return_value=SHA), mock.patch.object(manifest_policy, "gate"),
            mock.patch.object(merge, "cleanup"),
            mock.patch.object(merge, "require_merge_receipt", side_effect=seam_call) as seam,
            contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()),
        ):  # fmt: skip
            self.assertEqual(merge.main(["7"]), 0)
            seam.assert_called_once_with("7", target="7", verified_sha=SHA)
            self.assertEqual(order, ["seam", "gh"])
            order.clear()
            seam.side_effect = receipt_gate.ReceiptRefusedError("no_receipt")
            self.assertEqual(merge.main(["7"]), 1)
            self.assertEqual(order, [])

    def test_the_gate_asks_permits_about_merge(self) -> None:
        """require_merge_receipt consults authority_permits.permits('merge') for the session first."""
        with (
            mock.patch.dict(os.environ, {"CLAUDE_SESSION_ID": "spy-session"}),
            mock.patch.object(receipt_gate, "permits", return_value=DENIED) as spy,
            mock.patch.object(receipt_gate, "append_row"),
            mock.patch.object(receipt_gate, "resolve_mode", return_value=("enforce", False)),
            self.assertRaises(receipt_gate.ReceiptRefusedError) as caught,
        ):  # fmt: skip
            receipt_gate.require_merge_receipt("7", "/nowhere")
        self.assertIn("authority_denied", str(caught.exception))
        self.assertEqual(spy.call_args.args[:2], ("spy-session", "merge"))

    def test_the_gate_refuses_when_permits_omits_required_approval(self) -> None:
        """A guarded action cannot proceed if its permit verdict omits the approval requirement."""
        verdict = {"allow": True, "reason": "ok", "requires_approval": False, "authority_id": "auth-1"}
        with (
            mock.patch.dict(os.environ, {"CLAUDE_SESSION_ID": "spy-session"}),
            mock.patch.object(receipt_gate, "permits", return_value=verdict),
            mock.patch.object(receipt_gate, "append_row"),
            mock.patch.object(receipt_gate, "resolve_mode", return_value=("enforce", False)),
            self.assertRaises(receipt_gate.ReceiptRefusedError) as caught,
        ):  # fmt: skip
            refusal = receipt_gate.check_and_consume(
                "spy-session",
                [("merge", {})],
                datetime.now(timezone.utc),
                None,
                None,
            )
            self.assertEqual(refusal, ("merge", "approval_requirement_missing"))
            receipt_gate.require_merge_receipt("7", "/nowhere")
        self.assertIn("approval_requirement_missing", str(caught.exception))

    def test_merge_budget_lock_precedes_the_live_clock_read(self) -> None:
        """A receipt or grant expiring while the lock is held is checked at the post-lock time."""
        order: list[str] = []
        late = datetime.now(timezone.utc)

        @contextlib.contextmanager
        def waited(_session: str) -> Generator[bool, None, None]:
            order.append("lock")
            yield True

        def refused(_session: str, _action: str, now: datetime, **_kwargs: object) -> dict[str, bool | str]:
            order.append("permit")
            self.assertEqual(now, late)
            return {"allow": False, "reason": "authority_denied"}

        def tick(_zone: timezone) -> datetime:
            order.append("clock")
            return late

        with (
            mock.patch.object(merge_budget, "lock", side_effect=waited),
            mock.patch.object(receipt_gate, "datetime") as clock,
            mock.patch.object(receipt_gate, "permits", side_effect=refused),
        ):
            clock.now.side_effect = tick
            result = receipt_gate.check_and_consume("s1", [("merge", {})], None, None, None)
        self.assertEqual(result, ("merge", "authority_denied"))
        self.assertEqual(order, ["lock", "clock", "permit"])

    def test_loop_binding_uses_the_grant_after_lock_wait(self) -> None:
        """A grant renewal during lock contention cannot pair an old-loop receipt with a new-loop permit."""
        late = datetime.now(timezone.utc)
        allowed = {"allow": True, "requires_approval": True}
        proposal = {"artifact_sha": SHA}

        @contextlib.contextmanager
        def renewed(_session: str) -> Generator[bool, None, None]:
            yield True

        with (
            mock.patch.object(merge_budget, "lock", side_effect=renewed),
            mock.patch.object(receipt_gate, "permits", return_value=allowed),
            mock.patch.object(receipt_gate, "read_authority", return_value={"loop_id": "new-loop", "max_prs": 3}),
            mock.patch.object(receipt_gate, "executed_merges", return_value=0),
            mock.patch.object(receipt, "find_valid", return_value=(None, "foreign_loop")) as verify,
        ):
            result = receipt_gate.check_and_consume("s1", [("merge", proposal)], late, "old-loop", None)
        self.assertEqual(result, ("merge", "foreign_loop"))
        self.assertEqual(verify.call_args.args[3], "new-loop")

    def test_one_authority_snapshot_supplies_permit_and_loop(self) -> None:
        """A replacement grant between reads cannot lend its loop to an older allow verdict."""
        old = {
            "authority_id": "old",
            "loop_id": "old-loop",
            "denied": [],
            "approval_required_for": ["merge"],
            "max_prs": 3,
        }
        new = old | {"authority_id": "new", "loop_id": "new-loop", "denied": ["merge"]}
        proposal = {"artifact_sha": SHA}
        with (
            mock.patch.object(merge_budget, "lock", return_value=contextlib.nullcontext(True)),
            mock.patch.object(receipt_gate, "read_authority", side_effect=[old, new]) as read,
            mock.patch.object(receipt_gate, "executed_merges", return_value=0),
            mock.patch.object(receipt, "find_valid", return_value=(None, "foreign_loop")) as verify,
        ):
            result = receipt_gate.check_and_consume(
                "s1", [("merge", proposal)], datetime.now(timezone.utc), "stale-loop", None
            )
        self.assertEqual(result, ("merge", "foreign_loop"))
        read.assert_called_once()
        self.assertEqual(verify.call_args.args[3], "old-loop")
        with (
            mock.patch.object(receipt_gate, "authority_path", return_value=Path("/tmp/authority.json")),
            mock.patch.object(receipt_gate, "read_authority", side_effect=[old, new]) as direct_read,
            mock.patch.object(receipt_gate, "binding", return_value=None),
            mock.patch.object(merge_budget, "lock", return_value=contextlib.nullcontext(True)),
            mock.patch.object(receipt_gate, "resolve_mode", return_value=("enforce", False)),
            mock.patch.object(receipt_gate, "append_row"),
            mock.patch.dict(os.environ, {"CLAUDE_SESSION_ID": "s1"}),
            self.assertRaisesRegex(receipt_gate.ReceiptRefusedError, "binding_unknown"),
        ):
            receipt_gate.require_merge_receipt("7", "/repo", datetime.now(timezone.utc))
        direct_read.assert_called_once()
