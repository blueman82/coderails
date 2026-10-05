#!/usr/bin/env python3
"""Read-only Muninn store schema probe. `check()` returns None or a reason code; it never trusts `muninn --version`.

Reason codes: muninn_store_missing, muninn_schema_old (PRAGMA user_version != 2), muninn_schema_incomplete (a typed
`knowledge` column or the knowledge_fts / citation / knowledge_log table is missing). Opens the file with sqlite
mode=ro.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2
TYPED_COLUMNS = ("confidence", "valid_until", "sensitivity", "contradicts", "tags")
TABLES = ("knowledge_fts", "citation", "knowledge_log")
DB_NAME = "muninn.sqlite"


def store_path(data_home: str | Path | None = None) -> Path:
    """Return the store file: under the argument, else $MUNINN_HOME, else ~/.local/share/muninn."""
    home = data_home or os.environ.get("MUNINN_HOME") or Path.home() / ".local/share/muninn"
    return Path(home) / DB_NAME


def check(data_home: str | Path | None = None) -> str | None:
    """Return None when the store is a complete schema-v2 store, else the reason code."""
    db = store_path(data_home)
    if not db.is_file():
        return "muninn_store_missing"
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        try:
            if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                return "muninn_schema_old"
            columns = {r[1] for r in conn.execute("PRAGMA table_info(knowledge)")}
            names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
        finally:
            conn.close()
    except sqlite3.Error:
        return "muninn_schema_incomplete"  # unreadable or not sqlite: not a usable v2 store
    if not set(TYPED_COLUMNS) <= columns or not set(TABLES) <= names:
        return "muninn_schema_incomplete"
    return None


if __name__ == "__main__":
    reason = check()
    print(reason or "ok")
    raise SystemExit(0 if reason is None else 3)
