"""Verify the maintained Codex Python cutover roster and retired executable paths."""

from __future__ import annotations

import csv
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "codex"


class RetirementTests(unittest.TestCase):
    """Require complete contract rows and a shell-free installed package."""

    def test_contract_roster(self) -> None:
        """Every frozen contract identifies an existing Python implementation."""
        path = Path(__file__).with_name("codex_shell_retirement_contracts.tsv")
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.reader(stream, delimiter="\t"))
        self.assertEqual(
            rows[0], ["path", "group", "success", "failure", "stream", "exit", "environment", "invocation"]
        )
        self.assertGreater(len(rows), 1)
        for row in rows[1:]:
            self.assertEqual(len(row), 8)
            self.assertTrue(all(value.strip() for value in row), row)
            self.assertTrue(row[0].endswith(".py"), row[0])
            self.assertTrue((PACKAGE / row[0]).is_file(), row[0])

    def test_no_owned_shell_paths(self) -> None:
        """No installed operational wrapper, helper, or test keeps a shell path."""
        shells = sorted(
            str(path.relative_to(PACKAGE)) for path in PACKAGE.rglob("*.sh") if "node_modules" not in path.parts
        )
        self.assertEqual(shells, [])


if __name__ == "__main__":
    unittest.main()
