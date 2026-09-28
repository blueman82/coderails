#!/usr/bin/env python3
"""Lossless retention, storage budgets and concurrent lifecycle contracts."""

from __future__ import annotations

import gzip
import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.test_output_reader_test import READER, OutputFixtures


class RetentionTests(OutputFixtures):
    """Exercise archival, cleanup and concurrent reader protection."""

    def test_concurrent_completion_does_not_expire_in_progress_finalization(self) -> None:
        """A paused completion survives another completion's cleanup, then finishes normally."""
        script = """
import json
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import test_output as output
run = output.begin_run('claude', Path(sys.argv[2]), 'overlapping completion')
(run / 'output.log').write_bytes(b'first concurrent completion\\n')
print(json.dumps(str(run)), flush=True)
original = output.enforce_budget
def paused(*args):
    print('ready', flush=True)
    sys.stdin.readline()
    return original(*args)
output.enforce_budget = paused
print(output.finish_run(run, 1))
"""
        self.environment["CODERAILS_TEST_LOG_BUDGET_BYTES"] = "0"
        with subprocess.Popen(
            [sys.executable, "-c", script, str(READER.parent), str(self.project)],
            env=self.environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as process:
            assert process.stdout is not None
            first = Path(json.loads(process.stdout.readline()))
            self.assertEqual(process.stdout.readline().strip(), "ready")
            try:
                second = self.make_run(b"second concurrent completion\n")
                survived = (first / "output.log.gz").is_file()
            finally:
                stdout, stderr = process.communicate("\n", timeout=10)
            self.assertTrue(survived, "Concurrent cleanup expired an in-progress completion")
            self.assertEqual(process.returncode, 0, stderr)
            self.assertIn(str(first / "output.log.gz"), stdout)
        self.assertEqual(self.log_bytes(first), b"first concurrent completion\n")
        self.enforce_budget(second, 0)
        self.assertFalse((first / "output.log.gz").exists(), "Released lifecycle locks must not pin old logs")

    def test_cleanup_skips_in_progress_reader_then_expires_unlocked_archive(self) -> None:
        """A reader keeps its archive through selection and releases protection after completion."""
        run = self.make_run(b"reader must receive all bytes\n")
        protected = self.make_run(b"protected\n")
        script = """
import sys
sys.path.insert(0, sys.argv[1])
import test_output as output
original = output.select_output
def paused(*args):
    print('ready', flush=True)
    sys.stdin.readline()
    return original(*args)
output.select_output = paused
sys.argv = [sys.argv[1], 'read', sys.argv[2], '--all']
raise SystemExit(output.main())
"""
        with subprocess.Popen(
            [sys.executable, "-c", script, str(READER.parent), str(run)],
            env=self.environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as process:
            assert process.stdout is not None
            self.assertEqual(process.stdout.readline().strip(), "ready")
            try:
                self.enforce_budget(protected, 0)
                survived = (run / "output.log.gz").is_file()
            finally:
                stdout, stderr = process.communicate("\n", timeout=10)
            self.assertTrue(survived, "Cleanup expired an in-progress reader's archive")
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(json.loads(stdout)["text"], "reader must receive all bytes\n")
        self.enforce_budget(protected, 0)
        self.assertFalse((run / "output.log.gz").exists())

    def test_rotation_preserves_completed_binary_logs_and_active_capture(self) -> None:
        """Automatic lossless rotation archives completed runs while active logs remain writable."""
        script = """
import json
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from test_output import begin_run
run = begin_run('claude', Path(sys.argv[2]), "python checks.py --exact '€'")
(run / 'output.log').write_bytes(b'active partial\\n')
print(json.dumps(str(run)))
"""
        result = subprocess.run(
            [sys.executable, "-c", script, str(READER.parent), str(self.project)],
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        active = Path(json.loads(result.stdout))
        data = b"first\r\ninvalid:\xff\nlast"
        completed = self.make_run(data)
        self.assertTrue((completed / "output.log.gz").is_file())
        self.assertFalse((completed / "output.log").exists())
        self.assertEqual(gzip.decompress((completed / "output.log.gz").read_bytes()), data)
        self.assertEqual((active / "output.log").read_bytes(), b"active partial\n")
        self.assertFalse((active / "output.log.gz").exists())
        with (active / "output.log").open("ab") as stream:
            stream.write(b"still capturing\n")
        self.assertEqual(self.read(completed, "--all")["text"], data.decode(errors="replace"))
        self.assertEqual(self.read(completed, "--search", "invalid")["selected_ranges"], [[2, 2]])
        self.assertEqual(self.read(completed)["text"], "")

    def enforce_budget(self, protected: Path, budget: int) -> dict[str, Any]:
        """Invoke the public cleanup API against this test's isolated store."""
        script = """
import json
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from test_output import enforce_budget
print(json.dumps(enforce_budget(Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4]))))
"""
        result = subprocess.run(
            [sys.executable, "-c", script, str(READER.parent), str(self.store), str(protected), str(budget)],
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return cast("dict[str, Any]", json.loads(result.stdout))

    def test_budget_removes_oldest_completed_log_and_keeps_auditable_expiry(self) -> None:
        """Storage cleanup expires the oldest archive while retaining metadata and request evidence."""
        oldest = self.make_run(b"oldest\n")
        request = Path(self.read(oldest, "--all")["request_path"])
        original_request = request.read_bytes()
        newer = self.make_run(b"newer\n")
        protected = self.make_run(b"protected\n")
        budget = sum((run / "output.log.gz").stat().st_size for run in (newer, protected))
        original_size = (oldest / "output.log.gz").stat().st_size
        cleanup = self.enforce_budget(protected, budget)
        self.assertEqual(cleanup["remaining_compressed_bytes"], budget)
        self.assertIs(cleanup["over_budget"], False)
        self.assertFalse((oldest / "output.log.gz").exists())
        self.assertFalse((oldest / "output.log").exists())
        self.assertTrue((oldest / "run.json").is_file())
        tombstone = json.loads((oldest / "retention.json").read_text())
        self.assertEqual(tombstone["state"], "expired")
        self.assertEqual(tombstone["reason"], "storage-budget")
        self.assertEqual(tombstone["compressed_bytes"], original_size)
        self.assertEqual(tombstone["budget_bytes"], budget)
        self.assertTrue(tombstone["at"])
        self.assertEqual(request.read_bytes(), original_request)
        self.assertEqual(self.log_bytes(newer), b"newer\n")
        self.assertEqual(self.log_bytes(protected), b"protected\n")
        expired = self.invoke("read", str(oldest), "--all")
        self.assertNotEqual(expired.returncode, 0)
        self.assertIn("expired", (expired.stdout + expired.stderr).lower())

    def test_zero_budget_preserves_active_and_oversize_protected_run(self) -> None:
        """Cleanup may exceed its target when only active and current logs remain."""
        script = """
import json
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from test_output import begin_run
run = begin_run('claude', Path(sys.argv[2]), 'still running')
(run / 'output.log').write_bytes(b'active partial\\n')
print(json.dumps(str(run)))
"""
        result = subprocess.run(
            [sys.executable, "-c", script, str(READER.parent), str(self.project)],
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        active = Path(json.loads(result.stdout))
        old = self.make_run(b"old\n")
        protected = self.make_run(b"current larger than zero budget\n")
        cleanup = self.enforce_budget(protected, 0)
        self.assertIs(cleanup["over_budget"], True)
        self.assertEqual(cleanup["remaining_compressed_bytes"], (protected / "output.log.gz").stat().st_size)
        self.assertFalse((old / "output.log.gz").exists())
        self.assertEqual((active / "output.log").read_bytes(), b"active partial\n")
        self.assertFalse((active / "retention.json").exists())
        self.assertEqual(self.read(protected, "--all")["text"], "current larger than zero budget\n")


if __name__ == "__main__":
    unittest.main()
