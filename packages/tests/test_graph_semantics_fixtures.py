"""Run the maintained frozen semantic corpus through its Python entrypoint."""

import subprocess
import sys
import unittest
from pathlib import Path


class SemanticFixtureTests(unittest.TestCase):
    """Keep the package test runner connected to the maintained pure semantic corpus."""

    def test_frozen_corpus(self) -> None:
        """Every exact-result or atomic-refusal fixture must pass."""
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, str(root / "packages/graph-semantics/tests/run_fixtures.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
