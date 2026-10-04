"""Codex verification-volume ceiling recovers a stale lock left by a SIGKILLed hook."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "codex/hooks/scripts/verification_volume_ceiling.py"
CMD = "python3 packages/tests/test_codex_hooks.py"


def run_hook(data: Path, cwd: Path) -> str:
    """Run the hook once and return its stdout."""
    payload = json.dumps({"cwd": str(cwd), "tool_input": {"command": CMD}})
    env = {**os.environ, "PLUGIN_DATA": str(data)}
    done = subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True, env=env)
    return done.stdout


class CeilingLockTests(unittest.TestCase):
    """A dead-owner lock must not deny forever."""

    def test_dead_owner_lock_is_recovered(self) -> None:
        """Lock dir with a dead owner pid is stolen, the run is counted, nothing is denied."""
        with tempfile.TemporaryDirectory() as tmp:
            data, repo = Path(tmp) / "data", Path(tmp) / "repo"
            repo.mkdir()
            state = data / "verification-ceiling"
            state.mkdir(parents=True)
            subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "b"], check=True)
            lock = next(iter([state / "b__full-suite.count.lock"]))
            lock.mkdir()
            (lock / "owner").write_text(json.dumps({"pid": 4000000, "start": "", "ts": 0}))
            self.assertEqual(run_hook(data, repo), "")
            self.assertEqual((state / "b__full-suite.count").read_text(), "1\n")
            self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()
