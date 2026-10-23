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
    make_owner,
    make_repo,
    signed_receipt,
    store,
)

_loaded = set(sys.modules)
from scripts.lib import receipt_gate  # noqa: E402

for _name in set(sys.modules) - _loaded:  # keep Claude's scripts.* out of the cache: the Codex suites import their own
    if _name.startswith("scripts."):
        sys.modules.pop(_name)
        _parent, _, _leaf = _name.rpartition(".")
        if _parent in sys.modules:  # `from scripts.lib import x` would otherwise find the cached attribute
            vars(sys.modules[_parent]).pop(_leaf, None)

SHA = "f" * 40
DRIVER = """
import contextlib, os, sys, time
from pathlib import Path
from unittest import mock
sys.path.insert(0, os.environ["REPO_ROOT"])
from scripts import merge
from scripts.lib import action_receipt as ar
from scripts.lib import receipt_gate
from scripts.lib import git_common as git

fields = {"state": "OPEN", "headRefOid": os.environ["SHA"], "title": "t", "headRefName": "feature"}
patches = [
    mock.patch.object(git, "require_repo"), mock.patch.object(git, "main", return_value="main"),
    mock.patch.object(git, "protected", return_value=False), mock.patch.object(git, "sync_main_branch"),
    mock.patch.object(git, "pr_field", side_effect=lambda n, name, fb="": fields.get(name, fb)),
    mock.patch.object(merge, "verify_gates"), mock.patch.object(merge.manifest_policy, "gate"),
    mock.patch.object(merge, "cleanup"),
]
if os.environ.get("DELAY_PERMITS"):
    real_permits = receipt_gate.permits
    def delayed_permits(*args, **kwargs):
        verdict = real_permits(*args, **kwargs)
        time.sleep(0.3)
        return verdict
    patches.append(mock.patch.object(receipt_gate, "permits", side_effect=delayed_permits))
if os.environ.get("NO_SEAM"):  # negative control: the seam call removed
    patches.append(mock.patch.object(merge, "require_merge_receipt"))
if os.environ.get("BARRIER"):  # isolate the O_EXCL claim from the separate session-budget lock
    patches.append(mock.patch.object(receipt_gate.merge_budget, "lock", return_value=contextlib.nullcontext(True)))
def rendezvous(tag):  # both processes arrive before either goes on
    if not os.environ.get("BARRIER"):
        return
    Path(os.environ["BARRIER"], f"{tag}-{os.getpid()}").write_text("")
    deadline = time.time() + 15
    while len(list(Path(os.environ["BARRIER"]).glob(f"{tag}-*"))) < 2 and time.time() < deadline:
        time.sleep(0.01)
if os.environ.get("NAIVE_CLAIM"):  # negative control: exists()-then-write instead of O_EXCL
    def naive(path):
        marker = path.with_suffix(".consumed")
        seen = marker.exists()
        rendezvous("chk")
        if seen:
            return False
        marker.write_text("")
        return True
    patches += [mock.patch.object(ar, "consume", side_effect=naive),
                mock.patch.object(ar, "execute", side_effect=lambda p: True)]
elif os.environ.get("BARRIER"):  # both finish the is-it-consumed check before either claims
    real = ar.is_consumed
    def waiting(path):
        seen = real(path)
        rendezvous("in")
        return seen
    patches.append(mock.patch.object(ar, "is_consumed", side_effect=waiting))
for patch in patches:
    patch.start()
raise SystemExit(merge.main(["7"]))
"""


class MergeReceiptTests(unittest.TestCase):
    """A temp repo on main with origin acme/widgets, an owner key in the user-tier trust root, a fake gh."""

    plugin = ROOT  # the Codex test subclasses this with packages/codex

    def setUp(self) -> None:
        """Build the sandbox."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)
        self.repo = make_repo(self.tmp / "repo")
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
            f'case "$1 $2" in\n"pr view") echo \'{{"baseRefName":"main","headRefOid":"{SHA}"}}\';;\n'
            f'"pr merge") echo "$$" >> "{self.log}";;\nesac\n'
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
        self, rid: str = "r1", key: Path | None = None, session: str = "s1", number: int = 7, **over: object
    ) -> str:
        """Store a receipt for the merge as the owner would have signed it (bound to the live PR)."""
        bind = {"repository": REPOSITORY, "ref": "refs/heads/main", "sha": SHA}
        rec = signed_receipt(
            key or self.key, "merge", f"python3 scripts/merge.py {number}", str(self.repo), "main", bind, session,
            receipt_id=rid, **over,
        )  # fmt: skip
        store(self.loop, rec, session)
        return rid

    def grant(self, **over: object) -> None:
        """A live authority for s1."""
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
        """Run one child to completion; return (exit code, stderr)."""
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
        """How many times fake gh saw `pr merge`."""
        return len(self.log.read_text().splitlines()) if self.log.exists() else 0

    def refused(self, code: str, **env: str) -> None:
        """merge.py exits non-zero, names the reason, and never reaches gh pr merge."""
        rc, err = self.run_merge(**env)
        self.assertNotEqual(rc, 0, err)
        self.assertIn(code, err)
        self.assertEqual(self.merges(), 0)

    def test_no_receipt_is_denied(self) -> None:
        """(a) merge.py with no receipt: no_receipt, and gh is never called."""
        self.refused("no_receipt")

    def test_direct_invocation_consumes_and_executes_a_signed_receipt(self) -> None:
        """(e) No hook ran: merge.py verifies, consumes and marks executed; the replay is refused."""
        self.mint()
        rc, err = self.run_merge()
        self.assertEqual((rc, self.merges()), (0, 1), err)
        base = self.loop / "s1" / "receipts"
        self.assertTrue((base / "r1.consumed").exists() and (base / "r1.executed").exists())
        self.refused_after_one("consumed")

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
        """A further run is refused with `code` and does not add a second gh pr merge."""
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

    def test_no_session_is_denied(self) -> None:
        """No session id in the environment: nothing can be bound."""
        self.mint()
        rc, err = self.run_merge(CLAUDE_SESSION_ID="")
        self.assertNotEqual(rc, 0)
        self.assertIn("no_session", err)
        self.assertEqual(self.merges(), 0)

    def test_off_allows_and_advisory_does_not_block(self) -> None:
        """Explicit switches: `off` and `advisory` reach gh without a receipt."""
        for value in ("off", "advisory"):
            (self.repo / ".coderails").mkdir(exist_ok=True)
            (self.repo / ".coderails/workflow.config.yaml").write_text(f"action_authority: {value}\n")
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

    def hook_consume(self, command: str = "python3 scripts/merge.py 7") -> None:
        """Run the real PreToolUse hook on `command` so it consumes the receipt (phase 1)."""
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
        self.hook_consume("python3 scripts/merge.py 8")
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
