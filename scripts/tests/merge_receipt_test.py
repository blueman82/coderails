#!/usr/bin/env python3
"""scripts/merge.py is fail-closed on a signed, bound, single-use owner receipt, with or without the hook.

Each case runs the real merge.main in a child process with a fake `gh` on PATH that logs every `gh pr merge`.
Only the evidence gates (review/eval/manifest) and GitHub plumbing are stubbed; the receipt seam is real.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from hooks.scripts.tests.receipt_test_support import (  # noqa: E402
    REPOSITORY,
    git,
    make_owner,
    make_repo,
    signed_receipt,
    store,
)
from scripts.tests.merge_receipt_driver import DRIVER  # noqa: E402

_loaded = set(sys.modules)
from scripts.lib import receipt_gate  # noqa: E402

for _name in set(sys.modules) - _loaded:  # keep Claude's scripts.* out of the cache: the Codex suites import their own
    if _name.startswith("scripts."):
        sys.modules.pop(_name)
        _parent, _, _leaf = _name.rpartition(".")
        if _parent in sys.modules:  # `from scripts.lib import x` would otherwise find the cached attribute
            vars(sys.modules[_parent]).pop(_leaf, None)

SHA = "f" * 40


class MergeReceiptTests(unittest.TestCase):
    """A temp repo on main with origin acme/widgets, an owner key in the user-tier trust root, a fake gh."""

    plugin = ROOT  # the Codex test subclasses this with packages/codex

    def setUp(self) -> None:
        """Build the isolated repository, owner key, and fake GitHub client."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)
        self.repo = make_repo(self.tmp / "repo").resolve()
        (self.repo / ".coderails").mkdir()
        (self.repo / ".coderails/workflow.config.yaml").write_text("action_authority: enforce\ndiff_manifest: off\n")
        keys = self.tmp / "home" / ".coderails" / "keys"
        self.key, signers = make_owner(keys)
        signers.rename(keys / "receipt_signers")
        self.agent_key, _ = make_owner(self.tmp / "agent")
        self.loop = self.tmp / "loops"
        self.log = self.tmp / "gh.log"
        gh = self.tmp / "bin" / "gh"
        gh.parent.mkdir()
        gh.write_text(
            "#!/bin/sh\n"
            f'case "$1 $2" in\n"pr view") echo \'{{"number":7,"baseRefName":"main","headRefOid":"{SHA}"}}\';;\n'
            f'"pr merge") if [ "$GH_MERGE_FAIL" = 1 ]; then exit 1; fi; echo "$$" >> "{self.log}";;\n'
            '"pr list") case " $* " in *" -q "*) echo 7;; *) echo \'[{"number":7}]\';; esac;;\nesac\n'
        )
        gh.chmod(0o755)
        self.env = {
            k: v for k, v in os.environ.items() if k not in receipt_gate.SESSION_ENV
        } | {
            "HOME": str(self.tmp / "home"), "CLAUDE_AGENTIC_LOOP_DIR": str(self.loop), "CLAUDE_SESSION_ID": "s1",
            "PATH": f"{gh.parent}:{os.environ['PATH']}", "REPO_ROOT": str(self.plugin), "SHA": SHA,
            "PLUGIN_ROOT": str(self.plugin), "PLUGIN_DATA": str(self.tmp / "data"),
            "CLAUDE_DISCIPLINE_LOG": str(self.tmp / "d.log"),
        }  # fmt: skip

    def mint(
        self,
        rid: str = "r1",
        key: Path | None = None,
        session: str = "s1",
        number: int = 7,
        target: str | None = None,
        **over: object,
    ) -> str:
        """Store a receipt for the merge as the owner would have signed it (bound to the live PR)."""
        bind = {"repository": REPOSITORY, "ref": "refs/heads/main", "sha": SHA}
        command = f"python3 {self.plugin / 'scripts/merge.py'} {target or number} --expected-head {SHA}"
        rec = signed_receipt(
            key or self.key, "merge", command, str(self.repo),
            git(self.repo, "branch", "--show-current"), bind, session,
            receipt_id=rid, **over,
        )  # fmt: skip
        store(self.loop, rec, session)
        return rid

    def grant(self, **over: object) -> None:
        """Write a live session authority with optional overrides."""
        obj = {
            "authority_id": "auth-1", "loop_id": None, "session_id": "s1", "scope": ["code"], "denied": [],
            "max_prs": 3, "expires_at": "2999-01-01T00:00:00+00:00", "revocable": True,
            "approval_required_for": ["merge"], "granted_by": "command",
        } | over  # fmt: skip
        path = self.loop / "s1" / "authority.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj))

    def spawn(self, **env: str) -> subprocess.Popen[str]:
        """Start one merge.py child."""
        return subprocess.Popen(
            [sys.executable, "-c", DRIVER], cwd=self.repo, env=self.env | env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )  # fmt: skip

    def run_merge(self, **env: str) -> tuple[int, str]:
        """Run one child to completion; return its exit code and stderr."""
        child = self.spawn(**env)
        _, err = child.communicate(timeout=60)
        return child.returncode, err

    @staticmethod
    def close(children: list[subprocess.Popen[str]]) -> None:
        """Close the pipes of finished children."""
        for child in children:
            for stream in (child.stdout, child.stderr):
                if stream:
                    stream.close()

    def merges(self) -> int:
        """Count fake gh merge calls."""
        return len(self.log.read_text().splitlines()) if self.log.exists() else 0

    def refused(self, code: str, **env: str) -> None:
        """Require refusal before the first remote merge call."""
        rc, err = self.run_merge(**env)
        self.assertNotEqual(rc, 0, err)
        self.assertIn(code, err)
        self.assertEqual(self.merges(), 0)

    def test_no_receipt_is_denied(self) -> None:
        """(a) merge.py with no receipt: no_receipt, and gh is never called."""
        self.refused("no_receipt")

    def test_enforced_merge_needs_a_literal_expected_head(self) -> None:
        """A bare helper command cannot bind a signed receipt to an unseen future PR head."""
        self.mint()
        self.refused("binding_unknown", NO_EXPECTED="1")

    def test_direct_executable_receipt_cannot_authorise_python3_helper(self) -> None:
        """The supported Python command has a different hash from direct executable invocation."""
        command = f"{self.plugin / 'scripts/merge.py'} 7 --expected-head {SHA}"
        bind = {"repository": REPOSITORY, "ref": "refs/heads/main", "sha": SHA}
        rec = signed_receipt(
            self.key,
            "merge",
            command,
            str(self.repo),
            git(self.repo, "branch", "--show-current"),
            bind,
        )
        store(self.loop, rec, "s1")
        self.refused("hash_mismatch")

    def test_stale_expected_head_is_denied_before_receipt_use(self) -> None:
        """A moved PR head leaves the matching receipt unconsumed."""
        self.mint()
        self.refused("PR head changed", EXPECTED_SHA="a" * 40)
        self.assertFalse((self.loop / "s1" / "receipts" / "r1.consumed").exists())

    def test_direct_invocation_consumes_and_executes_a_signed_receipt(self) -> None:
        """(e) No hook ran: merge.py verifies, consumes and marks executed; the replay is refused."""
        self.mint()
        rc, err = self.run_merge()
        self.assertEqual((rc, self.merges()), (0, 1), err)
        base = self.loop / "s1" / "receipts"
        self.assertTrue((base / "r1.consumed").exists() and (base / "r1.executed").exists())
        self.refused_after_one("consumed")

    def test_direct_merge_rejects_a_receipt_for_another_pr(self) -> None:
        """Two PRs can share a target and head SHA; the signed PR number must still match."""
        self.mint(number=8)
        self.refused("hash_mismatch")
        base = self.loop / "s1" / "receipts"
        self.assertFalse((base / "r1.consumed").exists() or (base / "r1.executed").exists())

    def test_direct_merge_refuses_renamed_signed_receipt(self) -> None:
        """The direct merge path must bind a receipt's filename to its signed ID too."""
        self.mint()
        base = self.loop / "s1" / "receipts"
        (base / "r1.json").rename(base / "r2.json")
        self.refused("malformed")

    def test_two_receipts_cannot_exceed_one_merge_budget(self) -> None:
        """Distinct receipts must not let concurrent direct merges pass the same session cap."""
        self.grant(max_prs=1)
        self.mint("r1")
        self.mint("r2")
        children = [self.spawn(DELAY_PERMITS="1") for _ in range(2)]
        results = [child.communicate(timeout=60)[1] for child in children]
        self.assertEqual(self.merges(), 1, results)
        self.assertEqual(sorted(child.returncode for child in children), [0, 1], results)

    def refused_after_one(self, code: str, **env: str) -> None:
        """Require refusal after one earlier remote merge call."""
        rc, err = self.run_merge(**env)
        self.assertNotEqual(rc, 0, err)
        self.assertIn(code, err)
        self.assertEqual(self.merges(), 1)

    def test_rejected_set(self) -> None:
        """(c) wrong repository, wrong ref, stale SHA, unsigned, foreign-signed, expired, foreign session."""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        cases: tuple[tuple[str, dict[str, Any]], ...] = (
            ("repository_mismatch", {"repository": "github.com/evil/widgets"}),
            ("ref_mismatch", {"ref": "refs/heads/release"}),
            ("sha_mismatch", {"artifact_sha": "a" * 40}),
            ("signature_missing", {"signature": None}),
            ("signer_unknown", {"key": self.agent_key}),
            ("expired", {"expires_at": (past + timedelta(minutes=1)).isoformat(), "issued_at": past.isoformat()}),
            ("foreign_session", {"session_id": "other"}),
        )
        for code, over in cases:
            with self.subTest(code=code):
                self.mint(rid=code, **over)
                self.refused(code)
                (self.loop / "s1" / "receipts" / f"{code}.json").unlink()

    def test_authority_denied_and_max_prs_beat_a_valid_receipt(self) -> None:
        """(a) A valid receipt cannot override authority.denied or a spent max_prs (counted from .executed)."""
        self.mint()
        self.grant(denied=["merge"])
        self.refused("authority_denied")
        self.grant(denied=[], max_prs=1)
        self.mint("done")
        executed = self.loop / "s1" / "receipts" / "done.json"
        executed.with_suffix(".executed").write_text("")
        self.refused("max_prs_exceeded")
        self.assertFalse((self.loop / "s1" / "receipts" / "r1.consumed").exists())

    def test_advisory_still_obeys_live_merge_denial_and_cap(self) -> None:
        """A missing receipt is advisory, but a live authority denial or spent cap stops the remote merge."""
        (self.repo / ".coderails/workflow.config.yaml").write_text("action_authority: advisory\ndiff_manifest: off\n")
        self.grant(denied=["merge"])
        self.refused("authority_denied")
        self.grant(denied=[], max_prs=0)
        self.refused("max_prs_exceeded")

    def test_advisory_unreceipted_merge_spends_one_live_budget_slot(self) -> None:
        """One successful advisory merge without a receipt uses the live max_prs budget."""
        (self.repo / ".coderails/workflow.config.yaml").write_text("action_authority: advisory\ndiff_manifest: off\n")
        self.grant(max_prs=1)
        first, err = self.run_merge()
        self.assertEqual(first, 0, err)
        markers = list((self.loop / "s1" / "merges").glob("*.json"))
        self.assertEqual(len(markers), 1)
        self.assertEqual(
            json.loads(markers[0].read_text()),
            {"pr": "7", "repository": REPOSITORY, "ref": "refs/heads/main", "head": SHA, "state": "completed"},
        )
        self.refused_after_one("max_prs_exceeded")

    def test_confirmed_failed_advisory_merge_releases_budget_slot(self) -> None:
        """A failed remote merge whose PR remains open does not spend the session cap."""
        (self.repo / ".coderails/workflow.config.yaml").write_text("action_authority: advisory\ndiff_manifest: off\n")
        self.grant(max_prs=1)
        failed, _ = self.run_merge(GH_MERGE_FAIL="1")
        self.assertNotEqual(failed, 0)
        self.assertEqual(list((self.loop / "s1" / "merges").glob("*.json")), [])
        success, err = self.run_merge()
        self.assertEqual((success, self.merges()), (0, 1), err)

    def test_auto_and_branch_targets_can_use_exact_command_receipts(self) -> None:
        """The hook and direct seam accept receipts for supported merge.py targets."""
        git(self.repo, "switch", "-q", "-c", "feature/x")
        for target in ("auto", "feature/x"):
            with self.subTest(target=target):
                self.mint(rid=target.replace("/", "_"), target=target)
                rc, err = self.run_merge(MERGE_TARGET=target)
                self.assertEqual(rc, 0, err)

    def test_no_session_is_denied(self) -> None:
        """An absent session cannot receive a bound receipt."""
        self.mint()
        rc, err = self.run_merge(CLAUDE_SESSION_ID="")
        self.assertNotEqual(rc, 0)
        self.assertIn("no_session", err)
        self.assertEqual(self.merges(), 0)

    def test_off_allows_and_advisory_does_not_block(self) -> None:
        """Explicit switches: `off` and `advisory` reach gh without a receipt."""
        for value in ("off", "advisory"):
            (self.repo / ".coderails").mkdir(exist_ok=True)
            (self.repo / ".coderails/workflow.config.yaml").write_text(
                f"action_authority: {value}\ndiff_manifest: off\n"
            )
            rc, err = self.run_merge()
            self.assertEqual(rc, 0, err)
        self.assertEqual(self.merges(), 2)

    def test_concurrent_double_use_exactly_one_reaches_gh(self) -> None:
        """Two merge.py processes, one receipt, both past the consumed check (barrier): exactly one merges."""
        self.mint()
        barrier = self.tmp / "barrier"
        barrier.mkdir()
        children = [self.spawn(BARRIER=str(barrier)) for _ in range(2)]
        codes = sorted(child.wait(timeout=60) for child in children)
        self.close(children)
        self.assertEqual(len(list(barrier.glob("in-*"))), 2)  # the barrier really held both
        self.assertEqual((codes[0], codes[1] != 0, self.merges()), (0, True, 1))

    def test_negative_control_naive_claim_lets_both_through(self) -> None:
        """exists()-then-write (not O_EXCL) with the same barrier: both reach gh, so the test above has teeth."""
        self.mint()
        barrier = self.tmp / "barrier"
        barrier.mkdir()
        children = [self.spawn(BARRIER=str(barrier), NAIVE_CLAIM="c") for _ in range(2)]
        for child in children:
            child.communicate(timeout=60)
        self.assertEqual(self.merges(), 2)

    def test_negative_control_without_the_seam_merges_unreceipted(self) -> None:
        """Remove the seam call: a direct invocation merges with no receipt at all."""
        rc, err = self.run_merge(NO_SEAM="1")
        self.assertEqual((rc, self.merges()), (0, 1), err)

    def hook_consume(self, command: str | None = None) -> None:
        """Run the real PreToolUse hook on `command` so it consumes the receipt (phase 1)."""
        command = command or f"python3 {self.plugin / 'scripts/merge.py'} 7 --expected-head {SHA}"
        payload = {"session_id": "s1", "cwd": str(self.repo), "tool_name": "Bash", "tool_input": {"command": command}}
        done = subprocess.run(
            [sys.executable, str(self.plugin / "hooks/scripts/action_authority_gate.py")], input=json.dumps(payload),
            capture_output=True, text=True, env=self.env, cwd=self.repo, check=False,
        )  # fmt: skip
        self.assertNotIn("deny", done.stdout, done.stdout)

    def test_hook_then_merge_py_executes_once_for_the_hashed_pr(self) -> None:
        """Phase 1 consumes and records the hash; phase 2 claims .executed once, within 300 s, for that PR only."""
        self.mint()
        self.hook_consume()
        marker = self.loop / "s1" / "receipts" / "r1.consumed"
        note = json.loads(marker.read_text())
        self.assertEqual(note["number"], "7")
        self.assertEqual(len(note["hash"]), 64)
        rc, err = self.run_merge()
        self.assertEqual((rc, self.merges()), (0, 1), err)
        self.refused_after_one("consumed")

    def test_branch_target_hook_note_matches_direct_merge(self) -> None:
        """A branch command's hook note names the resolved PR, then direct merge accepts that receipt."""
        git(self.repo, "switch", "-q", "-c", "feature/x")
        self.mint(target="feature/x")
        self.hook_consume(f"python3 {self.plugin / 'scripts/merge.py'} feature/x --expected-head {SHA}")
        marker = self.loop / "s1" / "receipts" / "r1.consumed"
        self.assertEqual(json.loads(marker.read_text())["number"], "7")
        rc, err = self.run_merge(MERGE_TARGET="feature/x")
        self.assertEqual((rc, self.merges()), (0, 1), err)

    def test_hook_consumed_receipt_older_than_300_seconds_is_refused(self) -> None:
        """The two phases must be close in time: a stale hook note no longer licenses the merge."""
        self.mint()
        self.hook_consume()
        marker = self.loop / "s1" / "receipts" / "r1.consumed"
        old = time.time() - receipt_gate.HOOK_WINDOW_S - 60
        os.utime(marker, (old, old))
        self.refused("consumed")

    def test_hook_consumed_for_another_pr_is_refused(self) -> None:
        """A receipt the hook consumed for merge.py 8 does not license merge.py 7."""
        self.mint(number=8)
        self.hook_consume(f"python3 {self.plugin / 'scripts/merge.py'} 8 --expected-head {SHA}")
        self.refused("consumed")

    def test_two_merge_py_runs_after_one_hook_consume_exactly_one_executes(self) -> None:
        """The .executed claim is O_EXCL: of two merge.py runs behind one hook consume, one reaches gh."""
        self.mint()
        self.hook_consume()
        children = [self.spawn() for _ in range(2)]
        codes = sorted(child.wait(timeout=60) for child in children)
        self.close(children)
        self.assertEqual((codes[0], codes[1] != 0, self.merges()), (0, True, 1))


if __name__ == "__main__":
    unittest.main()
