#!/usr/bin/env python3
"""Pin the v2 receipt library with REAL ssh-keygen: one case per reason code, self-minting, replay, concurrency."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.receipt_test_support import REPOSITORY, make_owner, signed_receipt, store
from scripts.lib import action_receipt as ar

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime.now(timezone.utc)
COMMAND = "git push origin feature:main"
SHA = "a" * 40
BIND = {"repository": REPOSITORY, "ref": "refs/heads/main", "sha": SHA}


class Base(unittest.TestCase):
    """An owner key, an unrelated agent key, and an isolated loop dir."""

    keys: tempfile.TemporaryDirectory[str]
    key: Path
    signers: Path
    agent_key: Path

    @classmethod
    def setUpClass(cls) -> None:
        """Keys are created once."""
        cls.keys = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.keys.cleanup)
        cls.key, cls.signers = make_owner(Path(cls.keys.name) / "owner")
        cls.agent_key, _ = make_owner(Path(cls.keys.name) / "agent")

    def setUp(self) -> None:
        """Fresh loop dir per test."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)

    def receipt(self, key: Path | None = None, /, **over: object) -> dict[str, Any]:
        """A valid signed receipt for COMMAND bound to BIND."""
        return signed_receipt(key or self.key, "git_push", COMMAND, "/repo", "feature", BIND, "s1", NOW, **over)

    def proposed(self, bind: dict[str, str] | None = BIND) -> dict[str, Any]:
        """The action the hook sees."""
        return ar.proposed_action("git_push", COMMAND, "/repo", "feature", bind)

    def verify(self, rec: object, prop: dict[str, Any] | None = None, **over: object) -> tuple[bool, str]:
        """ar.verify with the default session, loop-less caller and the owner signers file."""
        args: dict[str, Any] = {"session_id": "s1", "loop_id": None, "consumed": False, "signers": self.signers}
        args.update(over)
        return ar.verify(rec, prop or self.proposed(), NOW, **args)


class VerifyTests(Base):
    """Every refusal has its own stable code, in the documented order."""

    def test_valid_signed_receipt(self) -> None:
        """(a) exact repository+ref+sha+command verifies."""
        self.assertEqual(self.verify(self.receipt()), (True, "ok"))

    def test_hash_covers_argv_cwd_branch_repository_ref(self) -> None:
        """Each input changes the hash."""
        base = ar.canonical_hash(["a"], "/c", "b", "r", "x")
        self.assertNotEqual(base, ar.canonical_hash(["z"], "/c", "b", "r", "x"))
        self.assertNotEqual(base, ar.canonical_hash(["a"], "/d", "b", "r", "x"))
        self.assertNotEqual(base, ar.canonical_hash(["a"], "/c", "z", "r", "x"))
        self.assertNotEqual(base, ar.canonical_hash(["a"], "/c", "b", "z", "x"))
        self.assertNotEqual(base, ar.canonical_hash(["a"], "/c", "b", "r", "z"))

    def test_self_minted_receipts_are_refused(self) -> None:
        """(b) unsigned JSON, an agent-made key and a body edited after signing."""
        unsigned = {**self.receipt(), "signature": None}
        self.assertEqual(self.verify(unsigned), (False, "signature_missing"))
        no_key = {k: v for k, v in unsigned.items() if k != "signature"}
        self.assertEqual(self.verify(no_key), (False, "signature_missing"))
        self.assertEqual(self.verify(self.receipt(self.agent_key)), (False, "signer_unknown"))
        edited = {**self.receipt(), "ref": "refs/heads/release/x"}
        self.assertEqual(self.verify(edited), (False, "signature_invalid"))
        self.assertEqual(self.verify({**self.receipt(), "signature": {"signer": "x"}}), (False, "signature_invalid"))
        self.assertEqual(self.verify(self.receipt(), signers=None), (False, "trust_root_missing"))

    def test_binding_mismatches(self) -> None:
        """(c) stale sha, wrong remote and wrong ref; order is hash, repository, ref, sha."""
        for field, value, code in (
            ("artifact_sha", "b" * 40, "sha_mismatch"),
            ("repository", "github.com/evil/widgets", "repository_mismatch"),
            ("ref", "refs/heads/release/x", "ref_mismatch"),
        ):
            with self.subTest(field):
                self.assertEqual(self.verify(self.receipt(**{field: value})), (False, code))
        moved = self.proposed({**BIND, "sha": "c" * 40})
        self.assertEqual(self.verify(self.receipt(), moved), (False, "sha_mismatch"))
        wrong_remote = self.proposed({**BIND, "repository": "github.com/evil/widgets"})
        self.assertEqual(self.verify(self.receipt(), wrong_remote), (False, "hash_mismatch"))  # the hash covers it too
        self.assertEqual(self.verify(self.receipt(), self.proposed(None)), (False, "hash_mismatch"))

    def test_refusal_table(self) -> None:
        """One case per remaining reason code, including the malformed shapes."""
        past = (NOW - timedelta(seconds=1)).isoformat()
        cases = {
            "expired": (self.verify(self.receipt(expires_at=past)), "expired"),
            "revoked": (self.verify(self.receipt(revoked=True)), "revoked"),
            "consumed": (self.verify(self.receipt(), consumed=True), "consumed"),
            "foreign_session": (self.verify(self.receipt(), session_id="s2"), "foreign_session"),
            "foreign_loop": (self.verify(self.receipt(loop_id="L1")), "foreign_loop"),
            "kind": (self.verify(self.receipt(), {**self.proposed(), "action": "merge"}), "kind_mismatch"),
        }
        for name, (got, code) in cases.items():
            with self.subTest(name):
                self.assertEqual(got, (False, code))

    def test_malformed(self) -> None:
        """(c) a missing artifact_sha, v1 shapes, extra fields and bad types are malformed, never downgraded."""
        good = self.receipt()
        v1 = {k: v for k, v in good.items() if k not in {"repository", "ref", "nonce", "signature"}}
        shapes: list[object] = [
            "x", {}, {"receipt_id": "r1"}, v1, {**good, "extra": 1}, {**good, "artifact_sha": None},
            {k: v for k, v in good.items() if k != "artifact_sha"}, {**good, "artifact_sha": ""},
            {**good, "single_use": False}, {**good, "single_use": "yes"}, {**good, "expires_at": "soon"},
            {**good, "nonce": None}, {**good, "repository": None}, {**good, "ref": ""},
        ]  # fmt: skip
        for index, shape in enumerate(shapes):
            with self.subTest(index):
                self.assertEqual(self.verify(shape), (False, "malformed"))


class StoreTests(Base):
    """Atomic write, O_EXCL consume, replay, torn files, revoke."""

    def test_replay_is_consumed(self) -> None:
        """(d) the second consume of the same receipt is refused."""
        rec = self.receipt()
        store(self.base, rec)
        first, code = ar.find_valid("s1", self.proposed(), NOW, None, self.base, True, self.signers)
        self.assertEqual((first and first["receipt_id"], code), (rec["receipt_id"], "ok"))
        again = ar.find_valid("s1", self.proposed(), NOW, None, self.base, True, self.signers)
        self.assertEqual(again, (None, "consumed"))

    def test_renamed_receipt_cannot_escape_its_consumed_marker(self) -> None:
        """Moving signed JSON to another filename cannot give it a fresh claim marker."""
        path = store(self.base, self.receipt())
        self.assertEqual(ar.find_valid("s1", self.proposed(), NOW, None, self.base, True, self.signers)[1], "ok")
        path.rename(path.with_name("renamed.json"))
        self.assertNotEqual(ar.find_valid("s1", self.proposed(), NOW, None, self.base, True, self.signers)[1], "ok")

    def test_peek_does_not_consume_and_revoke_stays_inspectable(self) -> None:
        """Advisory callers peek; a revoked receipt keeps its file but is refused."""
        path = store(self.base, self.receipt())
        for _ in range(2):
            self.assertEqual(ar.find_valid("s1", self.proposed(), NOW, None, self.base, False, self.signers)[1], "ok")
        self.assertTrue(ar.revoke_receipt(path))
        self.assertEqual(ar.find_valid("s1", self.proposed(), NOW, None, self.base, False, self.signers)[1], "revoked")
        self.assertFalse(ar.revoke_receipt(path.with_name("missing.json")))

    def test_unsafe_ids_foreign_dir_and_torn_write(self) -> None:
        """Unsafe ids give no path; a receipt copied to another session and torn files are never accepted."""
        for sid, rid in (("../x", "r"), ("s", "../r"), ("", "r"), ("s", ""), ("s", "a/b")):
            self.assertIsNone(ar.receipt_path(sid, rid, self.base))
        rec = self.receipt()
        copy = ar.receipt_path("s2", rec["receipt_id"], self.base)
        assert copy is not None
        ar.write_receipt(copy, rec)
        self.assertEqual(
            ar.find_valid("s2", self.proposed(), NOW, None, self.base, False, self.signers)[1], "foreign_session"
        )
        copy.write_text(json.dumps(rec)[:40])
        self.assertEqual(
            ar.find_valid("s2", self.proposed(), NOW, None, self.base, False, self.signers)[1], "malformed"
        )
        self.assertEqual(
            ar.find_valid("s3", self.proposed(), NOW, None, self.base, False, self.signers)[1], "no_receipt"
        )

    def test_concurrent_double_use_exactly_one_wins(self) -> None:
        """(e) 16 processes call find_valid(consume_it=True) on one receipt; exactly one gets it."""
        rec = self.receipt()
        store(self.base, rec)
        go = self.base / "go"
        code = (
            "import sys, time, json; sys.path.insert(0, sys.argv[1]);"
            "from pathlib import Path; from datetime import datetime, timezone;"
            "from scripts.lib import action_receipt as ar;"
            "p = json.loads(sys.argv[2]); base = Path(sys.argv[3]);"
            "[time.sleep(0.005) for _ in iter(lambda: not (base / 'go').exists(), False)];"
            "r, c = ar.find_valid('s1', p, datetime.now(timezone.utc), None, base, True, Path(sys.argv[4]));"
            "print(r['receipt_id'] if r else 'NONE:' + c)"
        )
        args = [sys.executable, "-c", code, str(ROOT), json.dumps(self.proposed()), str(self.base), str(self.signers)]
        procs = [subprocess.Popen(args, stdout=subprocess.PIPE, text=True) for _ in range(16)]
        time.sleep(0.5)
        go.write_text("")
        outs = [p.communicate()[0].strip() for p in procs]
        self.assertEqual(outs.count(rec["receipt_id"]), 1, outs)
        self.assertEqual(len([o for o in outs if o.startswith("NONE:")]), 15, outs)


if __name__ == "__main__":
    unittest.main()
