"""Stale mkdir-lock recovery: dead owners are stolen atomically, live or ambiguous owners never are."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.dir_lock import acquire_dir_lock, process_start, release_dir_lock

ROOT = Path(__file__).resolve().parents[3]

HOLDER = (
    "import sys,time\n"
    f"sys.path.insert(0,{str(ROOT)!r})\n"
    "from pathlib import Path\n"
    "from hooks.scripts.lib.dir_lock import acquire_dir_lock\n"
    "print(acquire_dir_lock(Path(sys.argv[1])), flush=True)\n"
    "time.sleep(60)\n"
)


def events(lock: Path) -> list[str]:
    """Return the reason codes logged next to the lock."""
    log = lock.parent / "lock-events.jsonl"
    if not log.is_file():
        return []
    return [json.loads(line)["reason"] for line in log.read_text(encoding="utf-8").splitlines()]


class DirLockTests(unittest.TestCase):
    """Each test owns a private lock directory and cleans up any child it starts."""

    def setUp(self) -> None:
        """Create a private lock path."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.lock = Path(temporary.name) / "state.json.lock"

    def holder(self) -> subprocess.Popen[str]:
        """Start a real child that acquires the lock and stays alive."""
        child = subprocess.Popen([sys.executable, "-c", HOLDER, str(self.lock)], stdout=subprocess.PIPE, text=True)
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        assert child.stdout is not None
        self.addCleanup(child.stdout.close)
        self.assertIn("True", child.stdout.readline())
        return child

    def acquire(self) -> tuple[bool, str]:
        """Acquire with a tiny retry budget."""
        return acquire_dir_lock(self.lock, attempts=2, delay=0.01)

    def make_lock(self, body: str | None) -> None:
        """Create a lock dir whose owner file is absent (None) or has the given text."""
        self.lock.mkdir()
        if body is not None:
            (self.lock / "owner").write_text(body, encoding="utf-8")

    def drop_lock(self) -> None:
        """Remove the lock dir and its owner file."""
        (self.lock / "owner").unlink() if (self.lock / "owner").exists() else None
        self.lock.rmdir()

    def old(self, seconds: float) -> None:
        """Backdate (or future-date, if negative) the lock directory."""
        stamp = time.time() - seconds
        os.utime(self.lock, (stamp, stamp))

    def test_fresh_acquire_and_owner_release(self) -> None:
        """A free lock is taken, owned by us, and released by us."""
        self.assertEqual(self.acquire(), (True, "acquired"))
        self.assertTrue(release_dir_lock(self.lock))
        self.assertFalse(self.lock.exists())

    def test_sigkilled_owner_is_stolen(self) -> None:
        """A SIGKILLed holder leaves a lock that the next caller recovers."""
        child = self.holder()
        os.kill(child.pid, signal.SIGKILL)
        child.wait()
        self.assertTrue(self.lock.is_dir())
        self.assertEqual(self.acquire(), (True, "lock_stolen_dead_owner"))
        self.assertEqual(events(self.lock), ["lock_stolen_dead_owner"])
        self.assertEqual(list(self.lock.parent.glob("*.stale.*")), [])

    def test_live_owner_never_stolen(self) -> None:
        """A live foreign owner yields lock_busy and keeps its lock."""
        self.holder()
        self.assertEqual(self.acquire(), (False, "lock_busy"))
        self.assertFalse(release_dir_lock(self.lock))
        self.assertTrue(self.lock.is_dir())
        self.assertEqual(events(self.lock), ["lock_busy"])

    def test_eperm_owner_is_alive(self) -> None:
        """PermissionError from kill(0) means alive, so the lock is not stolen."""
        self.make_lock(json.dumps({"pid": 999999, "start": "", "ts": 0}))
        with patch("os.kill", side_effect=PermissionError):
            self.assertEqual(self.acquire(), (False, "lock_busy"))

    def test_pid_reuse_start_mismatch_is_dead(self) -> None:
        """A live pid whose start time differs from the recorded one is a reused pid."""
        sleeper = subprocess.Popen(["sleep", "30"])
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        self.make_lock(json.dumps({"pid": sleeper.pid, "start": process_start(sleeper.pid)}))
        self.assertEqual(self.acquire(), (False, "lock_busy"))
        (self.lock / "owner").write_text(json.dumps({"pid": sleeper.pid, "start": "Thu Jan  1 00:00:00 1970"}))
        self.assertEqual(self.acquire(), (True, "lock_stolen_dead_owner"))

    def test_torn_owner_not_stolen_while_young(self) -> None:
        """Empty, torn or absent owner files are inside the mkdir-then-write window: never dead on their own."""
        for body in (None, "", '{"pid": 12'):
            with self.subTest(body=body):
                self.make_lock(body)
                self.assertEqual(self.acquire(), (False, "lock_busy"))
                self.drop_lock()

    def test_torn_owner_stolen_by_age(self) -> None:
        """Past the age bound a torn or absent owner is stolen with lock_stolen_age."""
        for body in (None, "", '{"pid": 12'):
            with self.subTest(body=body):
                self.make_lock(body)
                self.old(3600)
                self.assertEqual(self.acquire(), (True, "lock_stolen_age"))
                self.assertTrue(release_dir_lock(self.lock))

    def test_old_lock_with_live_owner_not_stolen(self) -> None:
        """Age alone never steals from a live owner."""
        self.holder()
        self.old(3600)
        self.assertEqual(self.acquire(), (False, "lock_busy"))

    def test_future_mtime_is_not_old(self) -> None:
        """Clock skew (mtime ahead of now) reads as young, so lock_busy."""
        self.make_lock(None)
        self.old(-3600)
        self.assertEqual(self.acquire(), (False, "lock_busy"))

    def test_two_stealers_race_exactly_one_steals(self) -> None:
        """Racing stealers: one rename wins, all serialize, and exactly one steal is logged."""
        child = self.holder()
        os.kill(child.pid, signal.SIGKILL)
        child.wait()
        go = self.lock.parent / "go"
        script = (
            "import sys,time\n"
            f"sys.path.insert(0,{str(ROOT)!r})\n"
            "from pathlib import Path\n"
            "from hooks.scripts.lib.dir_lock import acquire_dir_lock, release_dir_lock\n"
            f"go=Path({str(go)!r}); lock=Path({str(self.lock)!r})\n"
            "while not go.exists(): pass\n"
            "ok,_=acquire_dir_lock(lock,attempts=500,delay=0.01)\n"
            "time.sleep(0.05)\n"
            "release_dir_lock(lock)\n"
            "print(ok)\n"
        )
        procs = [subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True) for _ in range(4)]
        go.write_text("x")
        outs = [p.communicate()[0].strip() for p in procs]
        self.assertEqual(outs, ["True"] * 4)
        self.assertEqual(events(self.lock).count("lock_stolen_dead_owner"), 1)

    def test_release_by_non_owner_refused(self) -> None:
        """A process whose lock was stolen never removes the new holder's lock."""
        self.assertTrue(self.acquire()[0])
        (self.lock / "owner").write_text(json.dumps({"pid": os.getpid() + 1, "start": ""}))
        self.assertFalse(release_dir_lock(self.lock))
        self.assertTrue(self.lock.is_dir())

    def test_event_log_failure_is_fail_open(self) -> None:
        """An unwritable event log never raises or changes the lock result."""
        (self.lock.parent / "lock-events.jsonl").mkdir()  # a directory: append raises OSError
        self.make_lock(None)
        self.assertEqual(self.acquire(), (False, "lock_busy"))
        self.old(3600)
        self.assertEqual(self.acquire(), (True, "lock_stolen_age"))

    def test_event_rows_are_nonauthoritative_and_unique(self) -> None:
        """Each row carries ts, a distinct uuid event_id, the reason, schema and non_authoritative."""
        self.make_lock(None)
        self.acquire()
        self.old(3600)
        self.acquire()
        rows: list[Any] = [
            json.loads(x) for x in (self.lock.parent / "lock-events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual([r["reason"] for r in rows], ["lock_busy", "lock_stolen_age"])
        self.assertEqual(len({r["event_id"] for r in rows}), 2)
        for row in rows:
            self.assertEqual(row["schema"], "lock_event")
            self.assertIs(row["non_authoritative"], True)
            self.assertIn("ts", row)

    def test_malformed_stale_env_is_fail_open(self) -> None:
        """A garbage CLAUDE_LOCK_STALE_S falls back to the default bound instead of raising."""
        self.make_lock("{}")
        self.old(3600)
        with patch.dict(os.environ, {"CLAUDE_LOCK_STALE_S": "abc"}):
            self.assertEqual(self.acquire(), (True, "lock_stolen_age"))

    def test_foreign_host_owner_not_judged_by_local_pid(self) -> None:
        """A pid invisible locally but recorded by another host is not dead; only age can steal it."""
        owner = json.dumps({"pid": 4000000, "host": "some-other-host", "start": "", "ts": time.time()})
        self.make_lock(owner)
        self.assertEqual(self.acquire(), (False, "lock_busy"))
        self.old(3600)
        self.assertEqual(self.acquire(), (True, "lock_stolen_age"))

    def test_owner_records_host(self) -> None:
        """The owner file names the host so other hosts can refuse the pid check."""
        self.assertTrue(self.acquire()[0])
        self.assertEqual(json.loads((self.lock / "owner").read_text())["host"], socket.gethostname())

    def test_event_rows_identify_lock_and_parties(self) -> None:
        """Steal and busy rows name the lock, the judged owner pid and the acquirer pid."""
        self.make_lock(json.dumps({"pid": 4000000, "start": "", "ts": 0}))
        self.assertEqual(self.acquire(), (True, "lock_stolen_dead_owner"))
        release_dir_lock(self.lock)
        self.make_lock(None)
        self.acquire()
        rows = [json.loads(x) for x in (self.lock.parent / "lock-events.jsonl").read_text().splitlines()]
        self.assertEqual([r["lock"] for r in rows], [str(self.lock)] * 2)
        self.assertEqual(rows[0]["owner_pid"], 4000000)
        self.assertEqual(rows[0]["pid"], os.getpid())
        self.assertIsNone(rows[1]["owner_pid"])

    def test_codex_copy_is_byte_identical(self) -> None:
        """The vendored Codex copy cannot drift from the Claude primitive."""
        a = ROOT / "hooks/scripts/lib/dir_lock.py"
        b = ROOT / "packages/codex/hooks/scripts/lib/dir_lock.py"
        self.assertEqual(a.read_bytes(), b.read_bytes())


if __name__ == "__main__":
    unittest.main()
