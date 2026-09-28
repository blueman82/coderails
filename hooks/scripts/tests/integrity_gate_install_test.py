"""Expose complete privileged-install predicate parity to the root hook test runner."""

import subprocess
import sys
import unittest
from pathlib import Path


class IntegrityInstallParityTests(unittest.TestCase):
    """Run the two bounded installer suites through their standalone Python APIs."""

    def test_install_predicates_and_privileged_boundary(self) -> None:
        """All original predicates and owner/root boundary controls must pass."""
        directory = Path(__file__).resolve().parents[3] / "scripts/integrity-gate/tests"
        for name in ("install_preflight_test.py", "install_boundary_test.py"):
            with self.subTest(suite=name):
                result = subprocess.run(
                    [sys.executable, str(directory / name)], capture_output=True, text=True, check=False
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
