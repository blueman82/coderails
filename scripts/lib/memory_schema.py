#!/usr/bin/env python3
"""Read-only Muninn store schema probe. `check()` returns None or a reason code; it never trusts `muninn --version`.

Reason codes: muninn_store_missing, muninn_schema_old (PRAGMA user_version != 2), muninn_schema_incomplete (a required
column or table is missing, or an FTS trigger differs from Muninn schema v2). Opens the file with sqlite mode=ro.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2
TYPED_COLUMNS = ("confidence", "valid_until", "sensitivity", "contradicts", "tags")
TABLES = ("knowledge", "scope", "knowledge_fts", "citation", "knowledge_log")
TRIGGERS = {
    "knowledge_ai": """CREATE TRIGGER knowledge_ai AFTER INSERT ON knowledge BEGIN
        INSERT INTO knowledge_fts(rowid, text)
        SELECT new.id, new.text WHERE new.text IS NOT NULL; END""",
    "knowledge_ad": """CREATE TRIGGER knowledge_ad AFTER DELETE ON knowledge BEGIN
        INSERT INTO knowledge_fts(knowledge_fts, rowid, text)
        SELECT 'delete', old.id, old.text WHERE old.text IS NOT NULL; END""",
    "knowledge_au": """CREATE TRIGGER knowledge_au AFTER UPDATE ON knowledge BEGIN
        INSERT INTO knowledge_fts(knowledge_fts, rowid, text)
        SELECT 'delete', old.id, old.text WHERE old.text IS NOT NULL;
        INSERT INTO knowledge_fts(rowid, text)
        SELECT new.id, new.text WHERE new.text IS NOT NULL; END""",
}
KINDS = {"decision", "fact", "preference", "procedure", "lesson", "constraint"}
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
            columns = {r[1] for r in conn.execute("PRAGMA table_info(knowledge)")}
            schema = {r[0]: (r[1], r[2] or "") for r in conn.execute("SELECT name, type, sql FROM sqlite_master")}
            conn.execute(
                "SELECT rowid FROM knowledge_fts WHERE knowledge_fts MATCH ? LIMIT 1", ("coderails_schema_probe_zz",)
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return "muninn_schema_incomplete"  # unreadable or not sqlite: not a usable v2 store
    kind_check = re.search(
        r"\bkind\s+TEXT\s+NOT\s+NULL\s+CHECK\s*\(\s*kind\s+IN\s*\(([^)]*)\)",
        schema.get("knowledge", ("", ""))[1],
        re.I,
    )
    allowed_kinds: set[str] = set(re.findall(r"'([^']+)'", kind_check.group(1))) if kind_check else set()
    triggers = all(
        schema.get(name, ("", ""))[0] == "trigger" and _canonical_sql(schema[name][1]) == _canonical_sql(expected)
        for name, expected in TRIGGERS.items()
    )
    tables = all(schema.get(name, ("", ""))[0] == "table" for name in TABLES)
    fts_table = bool(
        re.match(
            r"CREATE\s+VIRTUAL\s+TABLE\s+knowledge_fts\s+USING\s+fts5\s*\(",
            schema.get("knowledge_fts", ("", ""))[1],
            re.I,
        )
    )
    if not (set(TYPED_COLUMNS) <= columns and tables and fts_table and allowed_kinds >= KINDS and triggers):
        return "muninn_schema_incomplete"
    return None


if __name__ == "__main__":
    reason = check()
    print(reason or "ok")
    raise SystemExit(0 if reason is None else 3)
