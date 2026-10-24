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

    def test_muninn_update_trigger_is_accepted(self) -> None:
        """Accept the Muninn trigger when an update changes the FTS result."""
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "store"
            path = store.create(home)
            with sqlite3.connect(path) as connection:
                connection.execute("INSERT INTO scope (key, label, kind) VALUES ('test', 'Test', 'global')")
                connection.execute(
                    "INSERT INTO knowledge (scope_id, kind, text, status, actor, created_at) "
                    "VALUES (1, 'fact', 'alpha', 'current', 'test', 1)"
                )
                connection.execute("UPDATE knowledge SET text = 'beta' WHERE id = 1")
                self.assertEqual(
                    connection.execute("SELECT rowid FROM knowledge_fts WHERE knowledge_fts MATCH 'alpha'").fetchall(),
                    [],
                )
                self.assertEqual(
                    connection.execute("SELECT rowid FROM knowledge_fts WHERE knowledge_fts MATCH 'beta'").fetchall(),
                    [(1,)],
                )
            self.assertIsNone(memory_schema.check(home))

    def test_muninn_trigger_with_comments_and_case_is_accepted(self) -> None:
        """Ignore SQL formatting changes that do not change trigger actions."""
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "store"
            path = store.create(home)
            with sqlite3.connect(path) as connection:
                connection.execute("DROP TRIGGER knowledge_au")
                connection.execute(
                    store.TRIGGERS["knowledge_au"]
                    .replace("AFTER UPDATE", "after /* format */ update")
                    .replace("INSERT INTO", "insert into")
                    .replace("SELECT", "select")
                )
            self.assertIsNone(memory_schema.check(home))

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

    def test_commented_update_effects_are_incomplete(self) -> None:
        """Reject a trigger whose apparent FTS writes are only comments."""
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "store"
            path = store.create(home)
            with sqlite3.connect(path) as connection:
                connection.execute("INSERT INTO scope (key, label, kind) VALUES ('test', 'Test', 'global')")
                connection.execute(
                    "INSERT INTO knowledge (scope_id, kind, text, status, actor, created_at) "
                    "VALUES (1, 'fact', 'alpha', 'current', 'test', 1)"
                )
                connection.execute("DROP TRIGGER knowledge_au")
                connection.execute(
                    "CREATE TRIGGER knowledge_au AFTER UPDATE ON knowledge BEGIN "
                    "/* INSERT INTO knowledge_fts(knowledge_fts, rowid, text) "
                    "SELECT 'delete', old.id, old.text; "
                    "INSERT INTO knowledge_fts(rowid, text) SELECT new.id, new.text; */ "
                    "SELECT 1; END"
                )
                connection.execute("UPDATE knowledge SET text = 'beta' WHERE id = 1")
                self.assertEqual(
                    connection.execute("SELECT rowid FROM knowledge_fts WHERE knowledge_fts MATCH 'alpha'").fetchall(),
                    [(1,)],
                )
                self.assertEqual(
                    connection.execute("SELECT rowid FROM knowledge_fts WHERE knowledge_fts MATCH 'beta'").fetchall(),
                    [],
                )
            self.assertEqual(memory_schema.check(home), "muninn_schema_incomplete")

    def test_update_trigger_with_false_predicates_is_incomplete(self) -> None:
        """Reject a trigger whose two FTS statements never write rows."""
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "store"
            path = store.create(home)
            with sqlite3.connect(path) as connection:
                connection.execute("INSERT INTO scope (key, label, kind) VALUES ('test', 'Test', 'global')")
                connection.execute(
                    "INSERT INTO knowledge (scope_id, kind, text, status, actor, created_at) "
                    "VALUES (1, 'fact', 'alpha', 'current', 'test', 1)"
                )
                connection.execute("DROP TRIGGER knowledge_au")
                connection.execute(
                    store.TRIGGERS["knowledge_au"]
                    .replace("WHERE old.text IS NOT NULL", "WHERE 0")
                    .replace("WHERE new.text IS NOT NULL", "WHERE 0")
                )
                connection.execute("UPDATE knowledge SET text = 'beta' WHERE id = 1")
                self.assertEqual(
                    connection.execute("SELECT rowid FROM knowledge_fts WHERE knowledge_fts MATCH 'alpha'").fetchall(),
                    [(1,)],
                )
                self.assertEqual(
                    connection.execute("SELECT rowid FROM knowledge_fts WHERE knowledge_fts MATCH 'beta'").fetchall(),
                    [],
                )
            self.assertEqual(memory_schema.check(home), "muninn_schema_incomplete")

    def test_ordinary_fts_table_is_incomplete(self) -> None:
        """Reject a table with the right name but no FTS MATCH index."""
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "store"
            path = store.create(home)
            with sqlite3.connect(path) as connection:
                connection.execute("DROP TABLE knowledge_fts")
                connection.execute("CREATE TABLE knowledge_fts (knowledge_fts TEXT, rowid INTEGER, text TEXT)")
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
