#!/usr/bin/env python3
"""Pin the action-receipt library: one case per reason code, foreign refusal, atomic consume, torn writes."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib import action_receipt as ar

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
ARGV = ["gh", "pr", "merge", "12"]
HASH = ar.canonical_hash(ARGV, "/repo", "feature/x")


def receipt(**over: object) -> dict[str, Any]:
    """A valid merge receipt, with overrides."""
    obj: dict[str, Any] = {
        "receipt_id": "r1",
        "authority_id": None,
        "session_id": "s1",
        "loop_id": "L1",
        "action": "merge",
        "exact_payload_hash": HASH,
        "artifact_sha": None,
        "scope": "pr-12",
        "issued_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "single_use": True,
        "revoked": False,
    }
    obj.update(over)
    return obj


def proposed(**over: object) -> dict[str, Any]:
    """The action the hook sees, matching receipt()."""
    obj: dict[str, Any] = {"action": "merge", "exact_payload_hash": HASH, "artifact_sha": None}
    obj.update(over)
    return obj


def verify(
    rec: object,
    prop: dict[str, Any] | None = None,
    session_id: str = "s1",
    loop_id: str | None = "L1",
    consumed: bool = False,
) -> tuple[bool, str]:
    """Run ar.verify with the default session and loop."""
    return ar.verify(rec, prop or proposed(), NOW, session_id, loop_id, consumed)


class VerifyTests(unittest.TestCase):
    """Every refusal has its own stable code; the matching receipt is the only ok."""

    def test_ok(self) -> None:
        """Exact match is accepted."""
        self.assertEqual(verify(receipt()), (True, "ok"))

    def test_hash_covers_argv_cwd_branch(self) -> None:
        """Different args, cwd or branch hash differently; same input hashes the same."""
        self.assertEqual(HASH, ar.canonical_hash(list(ARGV), "/repo", "feature/x"))
        for other in (
            ar.canonical_hash(["gh", "pr", "merge", "13"], "/repo", "feature/x"),
            ar.canonical_hash(ARGV, "/other", "feature/x"),
            ar.canonical_hash(ARGV, "/repo", "main"),
        ):
            self.assertNotEqual(HASH, other)
        self.assertEqual(verify(receipt(), proposed(exact_payload_hash=other)), (False, "hash_mismatch"))

    def test_refusal_table(self) -> None:
        """One case per reason code."""
        past = (NOW - timedelta(seconds=1)).isoformat()
        cases: list[tuple[str, tuple[bool, str]]] = [
            ("sha", verify(receipt(artifact_sha="aaa"), proposed(artifact_sha="bbb"))),
            ("sha_none", verify(receipt(artifact_sha="aaa"))),
            ("expired", verify(receipt(expires_at=past))),
            ("revoked", verify(receipt(revoked=True))),
            ("consumed", verify(receipt(), consumed=True)),
            ("foreign_session", verify(receipt(), session_id="s2")),
            ("foreign_loop", verify(receipt(), loop_id="L2")),
            ("malformed_str", verify("x")),
            ("malformed_missing", verify({"receipt_id": "r1"})),
            ("malformed_unknown", verify(receipt(extra=1))),
            ("malformed_expiry", verify(receipt(expires_at="soon"))),
            ("malformed_single", verify(receipt(single_use="yes"))),
            ("action", verify(receipt(), proposed(action="push"))),
        ]
        want = {
            "sha": "sha_mismatch",
            "sha_none": "sha_mismatch",
            "expired": "expired",
            "revoked": "revoked",
            "consumed": "consumed",
            "foreign_session": "foreign_session",
            "foreign_loop": "foreign_loop",
            "action": "kind_mismatch",
        }
        for name, result in cases:
            with self.subTest(name):
                self.assertEqual(result, (False, want.get(name, "malformed")))

    def test_unbound_loop_receipt_matches_any_loop(self) -> None:
        """A receipt with loop_id None is not loop-bound; a loop-bound one refuses a loop-less caller."""
        self.assertEqual(verify(receipt(loop_id=None), loop_id="L9"), (True, "ok"))
        self.assertEqual(verify(receipt(), loop_id=None), (False, "foreign_loop"))


class StoreTests(unittest.TestCase):
    """Atomic write, O_EXCL consume, torn writes, revoke stays inspectable."""

    def setUp(self) -> None:
        """Isolated loop dir."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_round_trip_and_revoke_keeps_file(self) -> None:
        """Write, read back, revoke: the file stays, flagged revoked, and is then refused."""
        path = ar.receipt_path("s1", "r1", self.base)
        assert path is not None
        self.assertTrue(ar.write_receipt(path, receipt()))
        self.assertEqual(ar.read_receipt(path), receipt())
        self.assertTrue(ar.revoke_receipt(path))
        self.assertTrue(path.is_file())
        self.assertEqual(ar.read_receipt(path), receipt())  # JSON never rewritten; tombstone is separate
        self.assertEqual(verify(ar.effective(path)), (False, "revoked"))
        self.assertEqual(ar.find_valid("s1", proposed(), NOW, "L1", self.base), (None, "revoked"))
        self.assertFalse(ar.revoke_receipt(path.with_name("missing.json")))

    def test_unsafe_ids(self) -> None:
        """Path-unsafe session or receipt ids give no path."""
        for sid, rid in (("../x", "r"), ("s", "../r"), ("", "r"), ("s", ""), ("s", "a/b")):
            self.assertIsNone(ar.receipt_path(sid, rid, self.base))

    def test_consume_race_exactly_one_wins(self) -> None:
        """Two threads race one single-use receipt; exactly one consumes."""
        path = ar.receipt_path("s1", "r1", self.base)
        assert path is not None
        ar.write_receipt(path, receipt())
        wins: list[bool] = []
        barrier = threading.Barrier(8)

        def go() -> None:
            barrier.wait()
            wins.append(ar.consume(path))

        threads = [threading.Thread(target=go) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(wins.count(True), 1)
        self.assertEqual(verify(ar.read_receipt(path), consumed=ar.is_consumed(path)), (False, "consumed"))

    def test_torn_write_is_malformed_never_accepted(self) -> None:
        """A truncated receipt, a leftover tmp file, or a missing receipt is never accepted."""
        path = ar.receipt_path("s1", "r1", self.base)
        assert path is not None
        path.parent.mkdir(parents=True)
        path.with_name(".r1.json.123.tmp").write_text(json.dumps(receipt()))  # crash before os.replace
        self.assertIsNone(ar.read_receipt(path))
        self.assertEqual(ar.find_valid("s1", proposed(), NOW, "L1", self.base), (None, "no_receipt"))
        path.write_text(json.dumps(receipt())[:40])  # torn in place
        self.assertIsNone(ar.read_receipt(path))
        self.assertEqual(ar.find_valid("s1", proposed(), NOW, "L1", self.base), (None, "malformed"))

    def test_find_valid_consumes_single_use_once(self) -> None:
        """find_valid returns the matching receipt and consumes it; the second call is refused."""
        path = ar.receipt_path("s1", "r1", self.base)
        assert path is not None
        ar.write_receipt(path, receipt())
        found, code = ar.find_valid("s1", proposed(), NOW, "L1", self.base, consume_it=True)
        self.assertEqual((found and found["receipt_id"], code), ("r1", "ok"))
        self.assertEqual(ar.find_valid("s1", proposed(), NOW, "L1", self.base, consume_it=True), (None, "consumed"))

    def test_find_valid_does_not_consume_by_default(self) -> None:
        """Advisory callers peek without burning the receipt."""
        path = ar.receipt_path("s1", "r1", self.base)
        assert path is not None
        ar.write_receipt(path, receipt())
        for _ in range(2):
            self.assertEqual(ar.find_valid("s1", proposed(), NOW, "L1", self.base)[1], "ok")

    def test_foreign_embedded_session_refused(self) -> None:
        """A receipt copied into another session's dir is refused as foreign_session."""
        path = ar.receipt_path("s2", "r1", self.base)
        assert path is not None
        ar.write_receipt(path, receipt())
        self.assertEqual(ar.find_valid("s2", proposed(), NOW, "L1", self.base), (None, "foreign_session"))

    def test_reusable_receipt_never_consumed(self) -> None:
        """single_use false: consume is not applied."""
        path = ar.receipt_path("s1", "r1", self.base)
        assert path is not None
        ar.write_receipt(path, receipt(single_use=False))
        for _ in range(2):
            self.assertEqual(ar.find_valid("s1", proposed(), NOW, "L1", self.base, consume_it=True)[1], "ok")


if __name__ == "__main__":
    unittest.main()
