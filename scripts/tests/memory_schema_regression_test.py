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

    def test_complete_v2_store_is_accepted(self) -> None:
        """Accept the pinned schema-v2 store before trying broken variants."""
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "store"
            store.create(home)
            self.assertIsNone(memory_schema.check(home))

    def test_missing_write_columns_are_incomplete(self) -> None:
        """Reject stores whose missing columns break ordinary inserts."""
        cases = (
            (
                "scope.label",
                "ALTER TABLE scope DROP COLUMN label",
                "INSERT INTO scope (key, label, kind) VALUES ('test', 'Test', 'global')",
            ),
            (
                "citation.quote",
                "ALTER TABLE citation DROP COLUMN quote",
                "INSERT INTO citation (knowledge_id, provider, thread_id, line, part, line_sha256, "
                "role, kind, quote) VALUES (1, 'codex', 'thread', 1, 1, 'hash', 'user', 'prompt', 'text')",
            ),
            (
                "knowledge_log.action",
                "DROP TABLE knowledge_log; CREATE TABLE knowledge_log "
                "(id INTEGER PRIMARY KEY, knowledge_id INTEGER NOT NULL, actor TEXT NOT NULL, at REAL NOT NULL)",
                "INSERT INTO knowledge_log (knowledge_id, action, actor, at) VALUES (1, 'add', 'test', 1)",
            ),
        )
        for name, mutation, insert in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary) / "store"
                path = store.create(home)
                with sqlite3.connect(path) as connection:
                    connection.executescript(mutation)
                    with self.assertRaises(sqlite3.OperationalError):
                        connection.execute(insert)
                self.assertEqual(memory_schema.check(home), "muninn_schema_incomplete")

    def test_missing_scope_kind_check_is_incomplete(self) -> None:
        """Reject a scope table that permits an unknown kind."""
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "store"
            path = store.create(home)
            with sqlite3.connect(path) as connection:
                connection.execute("DROP TABLE scope")
                connection.execute(store.SCOPE_SQL.replace("CHECK (kind IN ('git','dir','global'))", ""))
                connection.execute("INSERT INTO scope (key, label, kind) VALUES ('bad', 'Bad', 'bogus')")
            self.assertEqual(memory_schema.check(home), "muninn_schema_incomplete")

    def test_extra_knowledge_kind_is_incomplete(self) -> None:
        """Reject a knowledge table that permits an unknown kind."""
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "store"
            path = store.create(home)
            with sqlite3.connect(path) as connection:
                connection.execute("DROP TABLE knowledge")
                connection.execute(store.KNOWLEDGE_TABLE.replace("@KINDS@", str((*store.KINDS, "bogus"))))
                for trigger in store.TRIGGERS.values():
                    connection.execute(trigger)
                connection.execute("INSERT INTO scope (key, label, kind) VALUES ('test', 'Test', 'global')")
                connection.execute(
                    "INSERT INTO knowledge (scope_id, kind, text, status, actor, created_at) "
                    "VALUES (1, 'bogus', 'bad', 'current', 'test', 1)"
                )
            self.assertEqual(memory_schema.check(home), "muninn_schema_incomplete")

    def test_missing_confidence_check_is_incomplete(self) -> None:
        """Reject a knowledge table that permits an unknown confidence."""
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "store"
            path = store.create(home)
            ddl = store.KNOWLEDGE_TABLE.replace("@KINDS@", str(store.KINDS)).replace(
                "CHECK (confidence IS NULL OR confidence IN\n      ('observed','reported','inferred'))", ""
            )
            with sqlite3.connect(path) as connection:
                connection.execute("DROP TABLE knowledge")
                connection.execute(ddl)
                for trigger in store.TRIGGERS.values():
                    connection.execute(trigger)
                connection.execute("INSERT INTO scope (key, label, kind) VALUES ('test', 'Test', 'global')")
                connection.execute(
                    "INSERT INTO knowledge (scope_id, kind, text, status, actor, created_at, confidence) "
                    "VALUES (1, 'fact', 'bad', 'current', 'test', 1, 'bogus')"
                )
            self.assertEqual(memory_schema.check(home), "muninn_schema_incomplete")

    def test_missing_citation_index_is_incomplete(self) -> None:
        """Require the index used to locate citations by source position."""
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "store"
            path = store.create(home)
            with sqlite3.connect(path) as connection:
                connection.execute("DROP INDEX citation_target")
            self.assertEqual(memory_schema.check(home), "muninn_schema_incomplete")

    def test_missing_secure_delete_setting_is_incomplete(self) -> None:
        """Require the pinned FTS setting for search index deletion."""
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "store"
            path = store.create(home)
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE knowledge_fts_config SET v = 0 WHERE k = 'secure-delete'")
            self.assertEqual(memory_schema.check(home), "muninn_schema_incomplete")

    def test_missing_log_write_guards_are_incomplete(self) -> None:
        """Require both append-only triggers on the knowledge log."""
        for trigger in ("knowledge_log_no_update", "knowledge_log_no_delete"):
            with self.subTest(trigger=trigger), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary) / "store"
                path = store.create(home)
                with sqlite3.connect(path) as connection:
                    connection.execute(f"DROP TRIGGER {trigger}")
                self.assertEqual(memory_schema.check(home), "muninn_schema_incomplete")

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
