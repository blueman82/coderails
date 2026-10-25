"""Codex verification-volume ceiling recovers a stale lock left by a SIGKILLed hook."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "codex/hooks/scripts/verification_volume_ceiling.py"
CMD = "python3 packages/tests/test_codex_hooks.py"


def run_hook(data: Path, cwd: Path, command: str = CMD, loop: str = "loop1") -> str:
    """Run the hook once and return its stdout."""
    payload = json.dumps({"session_id": "s1", "cwd": str(cwd), "tool_input": {"command": command}})
    env = {
        **os.environ,
        "PLUGIN_DATA": str(data),
        "CODERAILS_AGENTIC_LOOP_DIR": str(data.parent / "loops"),
        "CLAUDE_LOOP_ID": loop,
        "CLAUDE_DISCIPLINE_LOG": str(data.parent / "discipline.log"),
    }
    done = subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr
    return done.stdout


def owned_state(repo: Path) -> dict[str, object]:
    """Minimal owned wave input for the optional mirror consumer, independent of the graph producer."""
    return {
        "schema_version": 3,
        "session_id": "s1",
        "loop_id": "loop1",
        "status": "in-progress",
        "work_units": {"1": {"worktree": str(repo)}},
        "graph": {"active_wave": {"nodes": ["U3[1]"]}, "nodes": {"U3[1]": {"status": "running"}}},
    }


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
            common = os.path.realpath(repo / ".git")
            key = hashlib.sha1((common + os.path.realpath(repo)).encode()).hexdigest()
            lock = state / f"{key}__full-suite.count.lock"
            lock.mkdir()
            (lock / "owner").write_text(json.dumps({"pid": 4000000, "start": "", "ts": 0}))
            self.assertEqual(run_hook(data, repo), "")
            self.assertEqual((state / f"{key}__full-suite.count").read_text(), "1\n")
            self.assertFalse(lock.exists())

    def test_regular_progress_lock_and_replacement_mode(self) -> None:
        """An unlocked native flock file permits a fresh mirror and keeps the progress file's mode."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data, repo = base / "data", base / "repo"
            subprocess.run(["git", "init", "-q", "-b", "b", str(repo)], check=True)
            progress = base / "loops/fixture/s1/progress.json"
            progress.parent.mkdir(parents=True)
            progress.write_text(json.dumps(owned_state(repo)))
            progress.chmod(0o640)
            lock = Path(f"{progress}.lock")
            lock.touch()
            self.assertEqual(run_hook(data, repo), "")
            state = json.loads(progress.read_text())
            self.assertEqual(state["work_units"]["1"]["verification"], {"run_all": 1})
            self.assertEqual(progress.stat().st_mode & 0o777, 0o640)
            self.assertTrue(lock.is_file())

    def test_busy_native_lock_skips_mirror_without_suppressing_denial(self) -> None:
        """A separate hook process cannot write under a held flock; its third counter run still denies."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data, repo = base / "data", base / "repo"
            subprocess.run(["git", "init", "-q", "-b", "b", str(repo)], check=True)
            progress = base / "loops/fixture/s1/progress.json"
            progress.parent.mkdir(parents=True)
            raw = json.dumps(owned_state(repo))
            progress.write_text(raw)
            with Path(f"{progress}.lock").open("a+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    results = [run_hook(data, repo) for _ in range(3)]
                    self.assertEqual(results[:2], ["", ""])
                    self.assertIn('"deny"', results[2])
                    self.assertEqual(progress.read_text(), raw)
                    state = json.loads(raw) | {"other_writer": "retained"}
                    progress.write_text(json.dumps(state))
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
            self.assertIn('"deny"', run_hook(data, repo))
            updated = json.loads(progress.read_text())
            self.assertEqual(updated["other_writer"], "retained")
            self.assertEqual(updated["work_units"]["1"]["verification"], {"run_all": 4})

    def test_effective_directory_charges_target(self) -> None:
        """Counter context follows the supported invocation directory."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data, origin, target = base / "data", base / "origin", base / "target space"
            for repo in (origin, target):
                subprocess.run(["git", "init", "-q", "-b", "b", str(repo)], check=True)
            quoted = shlex.quote(str(target))
            self.assertEqual(run_hook(data, origin, f"cd {quoted} && {CMD}"), "")
            self.assertEqual(run_hook(data, origin, f"env --chdir {quoted} {CMD}"), "")
            self.assertIn('"deny"', run_hook(data, target))

    def test_foreign_unknown_or_ambiguous_mirror_is_unchanged(self) -> None:
        """An optional mirror requires exact ownership and one registered running worktree unit."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data, target = base / "data", base / "target"
            subprocess.run(["git", "init", "-q", "-b", "b", str(target)], check=True)
            progress = base / "loops/fixture/s1/progress.json"
            progress.parent.mkdir(parents=True)
            variants: list[dict[str, object]] = [
                owned_state(target) | {"session_id": "foreign"},
                owned_state(target) | {"loop_id": "foreign"},
                owned_state(target) | {"graph": {}},
                owned_state(target) | {"schema_version": 2},
                owned_state(target) | {"status": "complete"},
                owned_state(target)
                | {"graph": {"active_wave": {"nodes": ["U3[2]"]}, "nodes": {"U3[2]": {"status": "running"}}}},
                owned_state(target)
                | {"graph": {"active_wave": {"nodes": ["U3[1]"]}, "nodes": {"U3[1]": {"status": "pending"}}}},
                owned_state(target) | {"work_units": {"1": {"worktree": str(target)}, "2": {"worktree": str(target)}}},
            ]
            for state in variants:
                with self.subTest(state=state):
                    raw = json.dumps(state)
                    progress.write_text(raw)
                    run_hook(data, target)
                    self.assertEqual(progress.read_text(), raw)
            raw = json.dumps(owned_state(target))
            progress.write_text(raw)
            run_hook(data, target, loop="")
            self.assertEqual(progress.read_text(), raw)

    def test_optional_mirror_io_errors_cannot_suppress_denial(self) -> None:
        """Corrupt content and a real incompatible lock path leave the authoritative counter active."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data, repo = base / "data", base / "repo"
            subprocess.run(["git", "init", "-q", "-b", "b", str(repo)], check=True)
            progress = base / "loops/fixture/s1/progress.json"
            progress.parent.mkdir(parents=True)
            progress.write_text("{broken")
            self.assertEqual([run_hook(data, repo) for _ in range(2)], ["", ""])
            Path(f"{progress}.lock").unlink()
            Path(f"{progress}.lock").mkdir()
            raw = json.dumps(owned_state(repo))
            progress.write_text(raw)
            self.assertIn('"deny"', run_hook(data, repo))
            self.assertEqual(progress.read_text(), raw)


if __name__ == "__main__":
    unittest.main()
