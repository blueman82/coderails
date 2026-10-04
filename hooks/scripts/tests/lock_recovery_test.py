"""Both in-hooks mkdir-lock sites recover from a SIGKILLed holder and still refuse live ones."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.loop_state_common import atomic_progress_update
from hooks.scripts.tests.native_hook_test_support import HookCase

ROOT = Path(__file__).resolve().parents[3]

PRELUDE = f"import sys,os,time\nsys.path.insert(0,{str(ROOT)!r})\nfrom pathlib import Path\n"
# Holds the lock the way the installed code does: a bare mkdir, so this works against old and new code alike.
HOLD = PRELUDE + (
    "lock=Path(sys.argv[1])\n"
    "try:\n"
    "    from hooks.scripts.lib.dir_lock import acquire_dir_lock\n"
    "    acquire_dir_lock(lock)\n"
    "except ImportError:\n"
    "    lock.mkdir()\n"
    "print('held', flush=True)\ntime.sleep(60)\n"
)
DIE_BEFORE_REPLACE = PRELUDE + (
    "import signal\n"
    "from hooks.scripts.lib.loop_state_common import atomic_progress_update\n"
    "real = os.replace\n"
    "os.replace = lambda s, d: (os.kill(os.getpid(), 9) if str(d).endswith('progress.json') else real(s, d))\n"
    "atomic_progress_update(Path(sys.argv[1]), lambda s: {**s, 'counter': 99})\n"
)


def bump(state: dict[str, Any]) -> dict[str, Any]:
    """Increment the counter."""
    return {**state, "counter": state["counter"] + 1}


def hold(lock: Path, case: unittest.TestCase) -> subprocess.Popen[str]:
    """Start a live child owning the lock."""
    child = subprocess.Popen([sys.executable, "-c", HOLD, str(lock)], stdout=subprocess.PIPE, text=True)
    case.addCleanup(child.wait)
    case.addCleanup(child.kill)
    assert child.stdout is not None
    case.addCleanup(child.stdout.close)
    child.stdout.readline()
    return child


def kill(child: subprocess.Popen[str]) -> None:
    """SIGKILL the child and reap it."""
    os.kill(child.pid, signal.SIGKILL)
    child.wait()


class ProgressLockRecoveryTests(unittest.TestCase):
    """atomic_progress_update after a crash."""

    def setUp(self) -> None:
        """Create a state file and a fast retry budget."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "progress.json"
        self.path.write_text(json.dumps({"counter": 0}), encoding="utf-8")
        self.lock = Path(f"{self.path}.lock")
        environment = patch.dict(os.environ, {"CLAUDE_HOOK_MAX_ATTEMPTS": "3", "CLAUDE_HOOK_SLEEP_S": "0.01"})
        environment.start()
        self.addCleanup(environment.stop)

    def counter(self) -> int:
        """Return the persisted counter."""
        return int(json.loads(self.path.read_text(encoding="utf-8"))["counter"])

    def test_sigkilled_holder_does_not_wedge_updates(self) -> None:
        """A killed holder's stale lock is recovered and the update lands."""
        kill(hold(self.lock, self))
        self.assertTrue(self.lock.is_dir())
        self.assertTrue(atomic_progress_update(self.path, bump))
        self.assertEqual(self.counter(), 1)
        self.assertFalse(self.lock.exists())

    def test_live_foreign_holder_refused(self) -> None:
        """Another live session's lock is never stolen and its state is untouched."""
        hold(self.lock, self)
        self.assertFalse(atomic_progress_update(self.path, bump))
        self.assertEqual(self.counter(), 0)
        self.assertTrue(self.lock.is_dir())

    def test_kill_between_tmp_write_and_replace_keeps_state(self) -> None:
        """SIGKILL before os.replace leaves the original state; the next update recovers."""
        child = subprocess.run([sys.executable, "-c", DIE_BEFORE_REPLACE, str(self.path)], check=False)
        self.assertEqual(child.returncode, -signal.SIGKILL)
        self.assertEqual(self.counter(), 0)
        self.assertTrue(self.lock.is_dir())
        self.assertTrue(atomic_progress_update(self.path, bump))
        self.assertEqual(self.counter(), 1)


class CeilingLockRecoveryTests(HookCase):
    """verification_volume_ceiling fails closed on a live lock but recovers a stale one."""

    def setUp(self) -> None:
        """Create a known branch."""
        super().setUp()
        self.repo = self.repository("repo", "unit-test")
        self.command = "python3 hooks/scripts/tests/run_all.py"
        self.counts = self.loop / "verification-ceiling"
        self.counts.mkdir(parents=True)
        self.lock = Path(f"{self.counts}/unit-test__run_all.count.lock")
        self.count = self.counts / "unit-test__run_all.count"

    def request(self) -> dict[str, Any]:
        """Build a native Bash request."""
        return {"tool_name": "Bash", "tool_input": {"command": self.command}, "cwd": str(self.repo)}

    def test_stale_lock_proceeds_and_counts(self) -> None:
        """A SIGKILLed holder no longer denies forever; the count increments."""
        kill(hold(self.lock, self))
        self.assertFalse(self.denied("verification_volume_ceiling", self.request()))
        self.assertEqual(self.count.read_text(encoding="utf-8").strip(), "1")

    def test_live_lock_still_denies_closed(self) -> None:
        """A live owner keeps the fail-closed deny."""
        hold(self.lock, self)
        self.assertTrue(self.denied("verification_volume_ceiling", self.request()))
        self.assertFalse(self.count.exists())


if __name__ == "__main__":
    unittest.main()
