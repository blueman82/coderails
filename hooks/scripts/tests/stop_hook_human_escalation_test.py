"""Expose native-provider Stop safety cases through an isolated test process."""

import subprocess
import sys
import unittest
from pathlib import Path


class NativeStopSuiteTests(unittest.TestCase):
    """Keep independent provider module names out of the root hook test interpreter."""

    def test_native_stop_escalation(self) -> None:
        """Execute all shared native Stop controls and retain their actual status/output."""
        root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            [sys.executable, str(root / "packages/tests/test_stop_hook_human_escalation.py")],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
