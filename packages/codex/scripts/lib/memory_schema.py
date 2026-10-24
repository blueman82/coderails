#!/usr/bin/env python3
"""Read-only Muninn store schema probe. `check()` returns None or a reason code; it never trusts `muninn --version`.

Reason codes: muninn_store_missing, muninn_schema_old (PRAGMA user_version != 2), muninn_schema_incomplete (a required
column, table, or FTS trigger action is missing). Opens the file with sqlite mode=ro.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2
TYPED_COLUMNS = ("confidence", "valid_until", "sensitivity", "contradicts", "tags")
TABLES = ("knowledge", "scope", "knowledge_fts", "citation", "knowledge_log")
TRIGGERS = ("knowledge_ai", "knowledge_ad", "knowledge_au")
KINDS = {"decision", "fact", "preference", "procedure", "lesson", "constraint"}
DB_NAME = "muninn.sqlite"
SQL_COMMENT_OR_STRING = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|/\*.*?\*/|--[^\n]*", re.S)


def store_path(data_home: str | Path | None = None) -> Path:
    """Return the store file: under the argument, else $MUNINN_HOME, else ~/.local/share/muninn."""
    home = data_home or os.environ.get("MUNINN_HOME") or Path.home() / ".local/share/muninn"
    return Path(home) / DB_NAME


def _trigger_actions(sql: str) -> str:
    """Remove comments and string literals before checking trigger statements."""

    def keep(match: re.Match[str]) -> str:
        token = match.group()
        return "'delete'" if token.casefold() == "'delete'" else ""

    return re.sub(r"\s+", "", SQL_COMMENT_OR_STRING.sub(keep, sql)).upper()


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
    effects = {
        "knowledge_ai": ("INSERTINTOKNOWLEDGE_FTS(ROWID,TEXT)SELECTNEW.ID,NEW.TEXT",),
        "knowledge_ad": ("INSERTINTOKNOWLEDGE_FTS(KNOWLEDGE_FTS,ROWID,TEXT)SELECT'DELETE',OLD.ID,OLD.TEXT",),
        "knowledge_au": (
            "INSERTINTOKNOWLEDGE_FTS(KNOWLEDGE_FTS,ROWID,TEXT)SELECT'DELETE',OLD.ID,OLD.TEXT",
            "INSERTINTOKNOWLEDGE_FTS(ROWID,TEXT)SELECTNEW.ID,NEW.TEXT",
        ),
    }
    triggers = all(
        schema.get(name, ("", ""))[0] == "trigger"
        and f"AFTER {event} ON KNOWLEDGE" in " ".join(schema[name][1].split()).upper()
        and all(effect in _trigger_actions(schema[name][1]) for effect in effects[name])
        for name, event in zip(TRIGGERS, ("INSERT", "DELETE", "UPDATE"))
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
