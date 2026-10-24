#!/usr/bin/env python3
"""Read-only Muninn store schema probe. `check()` returns None or a reason code; it never trusts `muninn --version`.

Reason codes: muninn_store_missing, muninn_schema_old (PRAGMA user_version != 2), muninn_schema_incomplete (the pinned
schema-v2 tables, index, triggers, or FTS setting differ). Opens the file with sqlite mode=ro.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2
EXPECTED_SCHEMA = {
    "scope": (
        "table",
        """CREATE TABLE scope (id INTEGER PRIMARY KEY,
        key TEXT NOT NULL UNIQUE, label TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('git','dir','global')))""",
    ),
    "knowledge": (
        "table",
        """CREATE TABLE knowledge (
        id INTEGER PRIMARY KEY, scope_id INTEGER NOT NULL REFERENCES scope(id),
        kind TEXT NOT NULL CHECK (kind IN ('decision','fact','preference','procedure','lesson','constraint')),
        text TEXT, status TEXT NOT NULL CHECK (status IN ('current','superseded','retracted','erased')),
        supersedes INTEGER REFERENCES knowledge(id),
        superseded_by INTEGER REFERENCES knowledge(id), retract_reason TEXT,
        actor TEXT NOT NULL, created_at REAL NOT NULL,
        confidence TEXT CHECK (confidence IS NULL OR confidence IN ('observed','reported','inferred')),
        valid_until REAL, sensitivity TEXT NOT NULL DEFAULT 'normal'
        CHECK (sensitivity IN ('normal','restricted')),
        contradicts INTEGER REFERENCES knowledge(id), tags TEXT,
        CHECK (status = 'erased' OR text IS NOT NULL))""",
    ),
    "knowledge_fts": (
        "table",
        """CREATE VIRTUAL TABLE knowledge_fts USING fts5(text,
        content='knowledge', content_rowid='id')""",
    ),
    "citation": (
        "table",
        """CREATE TABLE citation (id INTEGER PRIMARY KEY,
        knowledge_id INTEGER NOT NULL REFERENCES knowledge(id),
        provider TEXT NOT NULL, thread_id TEXT NOT NULL,
        line INTEGER NOT NULL, part INTEGER NOT NULL,
        line_sha256 TEXT NOT NULL, role TEXT NOT NULL, kind TEXT NOT NULL, ts TEXT,
        quote TEXT, span_start INTEGER, span_end INTEGER,
        state TEXT NOT NULL DEFAULT 'live' CHECK (state IN ('live','erased')))""",
    ),
    "citation_target": (
        "index",
        """CREATE INDEX citation_target
        ON citation(provider, thread_id, line, part)""",
    ),
    "knowledge_log": (
        "table",
        """CREATE TABLE knowledge_log (id INTEGER PRIMARY KEY,
        knowledge_id INTEGER NOT NULL,
        action TEXT NOT NULL CHECK (action IN ('add','supersede','superseded','retract','erase')),
        actor TEXT NOT NULL, at REAL NOT NULL)""",
    ),
    "knowledge_ai": (
        "trigger",
        """CREATE TRIGGER knowledge_ai AFTER INSERT ON knowledge BEGIN
        INSERT INTO knowledge_fts(rowid, text)
        SELECT new.id, new.text WHERE new.text IS NOT NULL; END""",
    ),
    "knowledge_ad": (
        "trigger",
        """CREATE TRIGGER knowledge_ad AFTER DELETE ON knowledge BEGIN
        INSERT INTO knowledge_fts(knowledge_fts, rowid, text)
        SELECT 'delete', old.id, old.text WHERE old.text IS NOT NULL; END""",
    ),
    "knowledge_au": (
        "trigger",
        """CREATE TRIGGER knowledge_au AFTER UPDATE ON knowledge BEGIN
        INSERT INTO knowledge_fts(knowledge_fts, rowid, text)
        SELECT 'delete', old.id, old.text WHERE old.text IS NOT NULL;
        INSERT INTO knowledge_fts(rowid, text)
        SELECT new.id, new.text WHERE new.text IS NOT NULL; END""",
    ),
    "knowledge_log_no_update": (
        "trigger",
        """CREATE TRIGGER knowledge_log_no_update
        BEFORE UPDATE ON knowledge_log BEGIN SELECT RAISE(ABORT, 'append-only'); END""",
    ),
    "knowledge_log_no_delete": (
        "trigger",
        """CREATE TRIGGER knowledge_log_no_delete
        BEFORE DELETE ON knowledge_log BEGIN SELECT RAISE(ABORT, 'append-only'); END""",
    ),
}
DB_NAME = "muninn.sqlite"
SQL_TOKENS = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|/\*.*?\*/|--[^\n]*|\s+|.", re.S)


def store_path(data_home: str | Path | None = None) -> Path:
    """Return the store file: under the argument, else $MUNINN_HOME, else ~/.local/share/muninn."""
    home = data_home or os.environ.get("MUNINN_HOME") or Path.home() / ".local/share/muninn"
    return Path(home) / DB_NAME


def _canonical_sql(sql: str) -> str:
    """Ignore comments, case, and whitespace outside SQL string literals."""
    tokens = (match.group() for match in SQL_TOKENS.finditer(sql))
    return "".join(
        token if token.startswith(("'", '"')) else token.upper()
        for token in tokens
        if not (token.isspace() or token.startswith(("/*", "--")))
    )


def check(data_home: str | Path | None = None) -> str | None:
    """Return None when the store is a complete schema-v2 store, else the reason code."""
    db = store_path(data_home)
    if not db.is_file():
        return "muninn_store_missing"
    try:
        conn = sqlite3.connect(f"{db.absolute().as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                return "muninn_schema_old"
            schema = {r[0]: (r[1], r[2] or "") for r in conn.execute("SELECT name, type, sql FROM sqlite_master")}
            conn.execute(
                "SELECT rowid FROM knowledge_fts WHERE knowledge_fts MATCH ? LIMIT 1", ("coderails_schema_probe_zz",)
            ).fetchone()
            secure_delete = conn.execute("SELECT v FROM knowledge_fts_config WHERE k = 'secure-delete'").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return "muninn_schema_incomplete"  # unreadable or not sqlite: not a usable v2 store
    objects_match = all(
        schema.get(name, ("", ""))[0] == object_type and _canonical_sql(schema[name][1]) == _canonical_sql(sql)
        for name, (object_type, sql) in EXPECTED_SCHEMA.items()
    )
    if not (objects_match and secure_delete == (1,)):
        return "muninn_schema_incomplete"
    return None


if __name__ == "__main__":
    reason = check()
    print(reason or "ok")
    raise SystemExit(0 if reason is None else 3)
