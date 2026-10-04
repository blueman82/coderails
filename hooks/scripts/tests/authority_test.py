#!/usr/bin/env python3
"""Pin the additive authority object: validator table, narrowing, revocation, exact-id reads, atomic writes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib import authority_object as ao

REPO = Path(__file__).resolve().parents[3]
CLI = REPO / "scripts" / "authority.py"
CRACK_ON = REPO / "hooks" / "scripts" / "crack_on_gate.py"
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def good(**over: object) -> dict[str, Any]:
    """A valid authority object, with overrides."""
    obj: dict[str, Any] = {
        "authority_id": "a1",
        "loop_id": None,
        "session_id": "s1",
        "scope": ["a", "b"],
        "denied": ["x"],
        "max_prs": 3,
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "revocable": True,
        "approval_required_for": ["merge"],
    }
    obj.update(over)
    return obj


class ValidatorTests(unittest.TestCase):
    """validate() is pure and reports every problem."""

    def test_table(self) -> None:
        """Each bad shape yields its error; the good object yields none."""
        self.assertEqual(ao.validate(good(), NOW), [])
        self.assertEqual(ao.validate(good(loop_id="L1"), NOW), [])
        merge_less = good(approval_required_for=["push"])
        cases: list[tuple[object, str]] = [
            ("x", "not_an_object"),
            (merge_less, "approval_required_for_must_include_merge"),
            (good(approval_required_for=[]), "approval_required_for_must_include_merge"),
            (good(max_prs=True), "max_prs"),
            (good(max_prs=-1), "max_prs"),
            (good(max_prs="3"), "max_prs"),
            (good(expires_at=(NOW - timedelta(seconds=1)).isoformat()), "expired"),
            (good(expires_at="2030-01-01T00:00:00"), "expires_at"),
            (good(expires_at="soon"), "expires_at"),
            (good(session_id="a/b"), "session_id"),
            (good(session_id=".."), "session_id"),
            (good(session_id=""), "session_id"),
            (good(scope="a"), "scope"),
            (good(denied=[1]), "denied"),
            (good(revocable="yes"), "revocable"),
            (good(loop_id=""), "loop_id"),
            (good(scope=["a"], denied=["a"]), "scope_denied_overlap"),
            (good(extra=1), "unknown:extra"),
        ]
        for obj, expected in cases:
            with self.subTest(expected=expected, obj=obj):
                self.assertIn(expected, ao.validate(obj, NOW))
        missing = good()
        del missing["denied"]
        self.assertIn("missing:denied", ao.validate(missing, NOW))

    def test_z_suffix_expiry_accepted(self) -> None:
        """A trailing Z parses as UTC."""
        self.assertEqual(ao.validate(good(expires_at="2026-01-01T01:00:00Z"), NOW), [])


class StorageTests(unittest.TestCase):
    """Exact-id reads and crash-safe writes."""

    def setUp(self) -> None:
        """Isolate the loop dir."""
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def put(self, directory: str, obj: dict[str, Any]) -> Path:
        """Write an authority.json under a session directory."""
        path = self.base / directory / "authority.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(obj))
        return path

    def test_read_exact_session_only(self) -> None:
        """A valid object reads back; a file planted in another session's dir is refused and traced."""
        obj = good(session_id="s1", expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
        self.put("s1", obj)
        self.put("s2", obj)
        self.assertEqual(ao.read_authority("s1", self.base), obj)
        self.assertIsNone(ao.read_authority("s2", self.base))
        rows = [json.loads(x) for x in (self.base / "s2" / "trace.jsonl").read_text().splitlines()]
        self.assertEqual([r["reason_code"] for r in rows], ["authority_refused_foreign"])

    def test_unsafe_ids_and_invalid_objects_grant_nothing(self) -> None:
        """Unsafe ids, expired objects and torn JSON all read as no authority."""
        self.put("s3", good(session_id="s3"))  # expired relative to real now
        (self.base / "s4").mkdir()
        (self.base / "s4" / "authority.json").write_text("{torn")
        for session in ("a/b", "..", "", "s3", "s4", "missing"):
            with self.subTest(session=session):
                self.assertIsNone(ao.read_authority(session, self.base))

    def test_crash_mid_write_keeps_old_file(self) -> None:
        """If os.replace fails, the old file is intact and no temp file is left; with no old file, none appears."""
        path = self.base / "s1" / "authority.json"
        with mock.patch("os.replace", side_effect=OSError("boom")):
            self.assertFalse(ao.write_authority(path, good()))
        self.assertFalse(path.exists())
        self.assertEqual(list(path.parent.iterdir()), [])
        self.assertTrue(ao.write_authority(path, good(max_prs=1)))
        with mock.patch("os.replace", side_effect=OSError("boom")):
            self.assertFalse(ao.write_authority(path, good(max_prs=2)))
        self.assertEqual(json.loads(path.read_text())["max_prs"], 1)
        self.assertEqual([p.name for p in path.parent.iterdir()], ["authority.json"])


class CliTests(unittest.TestCase):
    """create/inspect/narrow/revoke through the real script."""

    def setUp(self) -> None:
        """Isolate the loop dir via env."""
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.env = {**os.environ, "CLAUDE_AGENTIC_LOOP_DIR": str(self.base)}

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Invoke the CLI."""
        return subprocess.run(
            [sys.executable, str(CLI), *args], capture_output=True, text=True, env=self.env, check=False
        )

    def reasons(self, session: str = "s1") -> list[str]:
        """Trace reason codes for a session."""
        path = self.base / session / "trace.jsonl"
        return [json.loads(x)["reason_code"] for x in path.read_text().splitlines()] if path.is_file() else []

    def create(self, *extra: str) -> subprocess.CompletedProcess[str]:
        """Create s1 with scope a,b and max 3 PRs."""
        return self.run_cli("create", "--session", "s1", "--scope", "a,b", "--max-prs", "3", *extra)

    def test_every_refusal_has_a_stable_trace_code(self) -> None:
        """Each refusal path writes one refused row with its own low-cardinality reason code."""
        self.assertEqual(self.run_cli("create", "--session", "s2", "--max-prs", "1", "--scope", "a").returncode, 0)
        self.assertEqual(self.run_cli("narrow", "--session", "s2", "--max-prs", "5").returncode, 2)
        self.assertEqual(self.run_cli("narrow", "--session", "s2", "--scope", "z").returncode, 2)
        self.assertEqual(self.run_cli("narrow", "--session", "s2").returncode, 2)
        self.assertEqual(self.run_cli("create", "--session", "s2", "--max-prs", "1").returncode, 2)
        self.assertEqual(self.run_cli("revoke", "--session", "nope").returncode, 2)
        self.assertEqual(self.run_cli("create", "--session", "s3", "--max-prs", "1", "--not-revocable").returncode, 0)
        self.assertEqual(self.run_cli("revoke", "--session", "s3").returncode, 2)
        self.assertEqual(
            self.reasons("s2"),
            [
                "authority_created",
                "authority_refused_widen_max_prs",
                "authority_refused_widen_scope",
                "authority_refused_narrow_empty",
                "authority_refused_exists",
            ],
        )
        self.assertEqual(self.reasons("nope"), ["authority_refused_missing"])
        self.assertEqual(self.reasons("s3")[-1], "authority_refused_not_revocable")

    def test_missing_expired_malformed_are_distinct(self) -> None:
        """The 'no valid object' refusal says why, in the trace."""
        (self.base / "e").mkdir()
        (self.base / "e" / "authority.json").write_text(json.dumps(good(session_id="e")))  # expired
        (self.base / "m").mkdir()
        (self.base / "m" / "authority.json").write_text("{torn")
        for session in ("e", "m", "x"):
            self.assertEqual(self.run_cli("revoke", "--session", session).returncode, 2)
        self.assertEqual(self.reasons("e"), ["authority_refused_expired"])
        self.assertEqual(self.reasons("m"), ["authority_refused_malformed"])
        self.assertEqual(self.reasons("x"), ["authority_refused_missing"])

    def test_create_inspect_always_requires_merge(self) -> None:
        """Create writes a valid object whose approval list always has merge; a second create is refused."""
        result = self.create("--approval-for", "push")
        self.assertEqual(result.returncode, 0, result.stderr)
        shown = json.loads(self.run_cli("inspect", "--session", "s1").stdout)
        self.assertEqual(shown["approval_required_for"], ["merge", "push"])
        self.assertIsNone(shown["loop_id"])
        self.assertEqual(self.create().returncode, 2)
        self.assertEqual(self.reasons(), ["authority_created", "authority_refused_exists"])

    def test_narrow_only_shrinks(self) -> None:
        """Subset scope and lower max_prs are applied; wider or larger values are refused and change nothing."""
        self.create()
        self.assertEqual(self.run_cli("narrow", "--session", "s1", "--scope", "a", "--max-prs", "2").returncode, 0)
        shown = json.loads(self.run_cli("inspect", "--session", "s1").stdout)
        self.assertEqual((shown["scope"], shown["max_prs"]), (["a"], 2))
        for args in (("--scope", "a,c"), ("--scope", "b"), ("--max-prs", "9"), ()):
            with self.subTest(args=args):
                self.assertEqual(self.run_cli("narrow", "--session", "s1", *args).returncode, 2)
        after = json.loads(self.run_cli("inspect", "--session", "s1").stdout)
        self.assertEqual((after["scope"], after["max_prs"]), (["a"], 2))
        self.assertEqual(
            [r for r in self.reasons() if not r.startswith("authority_refused")],
            ["authority_created", "authority_narrowed"],
        )
        self.assertEqual(len(self.reasons()), 6)  # plus one refused row per refusal above

    def test_revoke(self) -> None:
        """A revocable object is removed and traced; a non-revocable one is refused and stays."""
        self.create()
        self.assertEqual(self.run_cli("revoke", "--session", "s1").returncode, 0)
        self.assertFalse((self.base / "s1" / "authority.json").exists())
        self.assertEqual(self.run_cli("create", "--session", "s2", "--max-prs", "1", "--not-revocable").returncode, 0)
        refused = self.run_cli("revoke", "--session", "s2")
        self.assertEqual(refused.returncode, 2)
        self.assertTrue((self.base / "s2" / "authority.json").exists())
        self.assertEqual(self.reasons(), ["authority_created", "authority_revoked"])
        self.assertEqual(self.reasons("s2"), ["authority_created", "authority_refused_not_revocable"])

    def test_unsafe_session_ids_refused_not_sanitised(self) -> None:
        """A slash or dotdot id is refused outright; nothing is written."""
        for session in ("a/b", "..", "a..b"):
            with self.subTest(session=session):
                result = self.run_cli("create", "--session", session, "--max-prs", "1")
                self.assertEqual(result.returncode, 2)
        self.assertEqual(list(self.base.iterdir()), [])

    def test_foreign_session_file_not_inspectable(self) -> None:
        """A file copied into another session's directory is not returned for that session."""
        self.create()
        (self.base / "s9").mkdir()
        (self.base / "s9" / "authority.json").write_text((self.base / "s1" / "authority.json").read_text())
        self.assertEqual(json.loads(self.run_cli("inspect", "--session", "s9").stdout), None)
        self.assertEqual(self.run_cli("narrow", "--session", "s9", "--max-prs", "1").returncode, 2)
        self.assertEqual(self.reasons("s9"), ["authority_refused_foreign", "authority_refused_foreign"])

    def test_crack_on_stamp_does_not_create_authority(self) -> None:
        """Negative control: the existing stamp writes only its flag, never an authority object."""
        payload = {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "please crack on"}
        env = {**self.env, "CLAUDE_DISCIPLINE_LOG": str(self.base / "d.log")}
        result = subprocess.run(
            [sys.executable, str(CRACK_ON)], input=json.dumps(payload), capture_output=True, text=True, env=env
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.base / "s1" / "crack_on_active").is_file())
        self.assertFalse((self.base / "s1" / "authority.json").exists())


if __name__ == "__main__":
    unittest.main()
