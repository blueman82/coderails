"""Reject repeated property names in both published config schemas."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class SchemaDuplicateTests(unittest.TestCase):
    """Normal JSON parsing hides duplicate names by keeping the last value."""

    def test_no_duplicate_keys(self) -> None:
        """Every object in each provider schema has unique keys."""

        def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
            values: dict[str, object] = {}
            for key, value in pairs:
                self.assertFalse(key in values, key)
                values[key] = value
            return values

        for path in (ROOT / "config.schema.json", ROOT / "packages/codex/config.schema.json"):
            with self.subTest(path=path):
                json.loads(path.read_text(), object_pairs_hook=unique_pairs)


if __name__ == "__main__":
    unittest.main()
