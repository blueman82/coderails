"""Check that the fake Muninn CLI refuses value flags with no value."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.tests.fake_muninn_case import StoreCase  # noqa: E402


class MissingAddValues(StoreCase):
    """Check every value-taking add flag at the CLI boundary."""

    def test_value_flags_need_values(self) -> None:
        """Return one JSON refusal for a flag with no value."""
        for flag in (
            "--kind",
            "--text",
            "--supersedes",
            "--confidence",
            "--valid-until",
            "--sensitivity",
            "--contradicts",
            "--scope-loop",
            "--cite",
            "--quote",
            "--tag",
        ):
            with self.subTest(flag=flag):
                self.assertEqual(self.muninn("know", "add", flag), (2, {"error": "bad_usage"}))


if __name__ == "__main__":
    unittest.main()
