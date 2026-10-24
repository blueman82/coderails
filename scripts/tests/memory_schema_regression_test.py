"""Reject incomplete stores without changing the store or nearby files."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.lib import memory_schema  # noqa: E402
from scripts.tests import fake_muninn_store as store  # noqa: E402


class SchemaRegression(unittest.TestCase):
    """Check malformed stores and paths with independent temporary files."""

    def test_missing_scope_table_is_incomplete(self) -> None:
        """Reject a store that cannot resolve knowledge scopes."""
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "store"
            path = store.create(home)
            with sqlite3.connect(path) as connection:
                connection.execute("DROP TABLE scope")
            self.assertEqual(memory_schema.check(home), "muninn_schema_incomplete")

    def test_noop_update_trigger_is_incomplete(self) -> None:
        """Reject a trigger that names FTS but does not update it."""
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "store"
            path = store.create(home)
            with sqlite3.connect(path) as connection:
                connection.execute("DROP TRIGGER knowledge_au")
                connection.execute(
                    "CREATE TRIGGER knowledge_au AFTER UPDATE ON knowledge BEGIN SELECT 'knowledge_fts'; END"
                )
            self.assertEqual(memory_schema.check(home), "muninn_schema_incomplete")

    def test_hash_in_path_does_not_create_sibling(self) -> None:
        """Read a path with a URI fragment character without creating a file."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "has#hash"
            store.create(home)
            before = set(root.iterdir())
            self.assertIsNone(memory_schema.check(home))
            self.assertEqual(set(root.iterdir()), before)


if __name__ == "__main__":
    unittest.main()
