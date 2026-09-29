"""Exercise real concurrent Codex graph writers on one isolated state file."""

from __future__ import annotations

import fcntl
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from packages.tests.provider_fixture import Provider


class CodexConcurrencyTests(unittest.TestCase):
    """Concurrent native CLI processes must retain both graph transitions."""

    def test_distinct_respawns_survive_concurrent_writers(self) -> None:
        """Both writers must retain their transitions while sharing one state lock."""
        with tempfile.TemporaryDirectory() as scratch:
            provider = Provider(Path(scratch), "codex")
            state = provider.state(("U3[1]", "U3[2]"))
            for node in state["graph"]["nodes"].values():
                node.update(
                    status="stale",
                    outcome="stale",
                    stale_check={"checked": True, "method": "native status", "result": "stalled"},
                )
            provider.write(state)
            command = [sys.executable, str(provider.plugin / "skills/agentic-loop/scripts/graph.py")]
            processes: list[subprocess.Popen[str]] = []
            lock_path = Path(f"{provider.path}.lock")
            before = provider.path.read_bytes()
            with lock_path.open("a+", encoding="utf-8") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                for identifier in ("U3[1]", "U3[2]"):
                    processes.append(
                        subprocess.Popen(
                            [
                                *command,
                                "respawn-stale",
                                str(provider.path),
                                "--session",
                                provider.session,
                                "--node",
                                identifier,
                                "--reason",
                                "checked stalled child",
                            ],
                            cwd=provider.home,
                            env=provider.environment,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                        )
                    )
                time.sleep(0.15)
                blocked = all(process.poll() is None for process in processes)
                held_bytes = provider.path.read_bytes()
                fcntl.flock(lock, fcntl.LOCK_UN)
            outputs = [process.communicate(timeout=15) for process in processes]
            self.assertTrue(blocked, "a writer bypassed the Codex state lock")
            self.assertEqual(held_bytes, before)
            for process, (stdout, stderr) in zip(processes, outputs):
                self.assertEqual(process.returncode, 0, stderr)
                self.assertEqual(json.loads(stdout)["generation"], 1)
            updated = provider.read()
            self.assertEqual(updated["revision"], state["revision"] + 2)
            for identifier in ("U3[1]", "U3[2]"):
                node = updated["graph"]["nodes"][identifier]
                self.assertEqual(node["status"], "pending")
                self.assertEqual(node["respawn"]["generation"], 1)
                self.assertEqual(node["respawn"]["intent"]["reason"], "checked stalled child")
            self.assertEqual(provider.success("inspect")["ready"], ["U3[1]", "U3[2]"])


if __name__ == "__main__":
    unittest.main()
