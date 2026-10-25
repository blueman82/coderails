"""Schema-v2 sqlite store and synthetic-transcript reader behind the fake `muninn` CLI (test infrastructure only).

The DDL is copied from Muninn's store_schema.py (63aa1bd5): scope, knowledge with the typed columns and the three FTS
triggers, knowledge_fts, citation, knowledge_log. `create` can build deliberately broken variants for negative controls.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

DB_NAME = "muninn.sqlite"
QUOTE_MIN, QUOTE_MAX = 12, 300
TAG = re.compile(r"[a-z0-9_-]{1,32}")
LOOP = re.compile(r"[A-Za-z0-9_.-]{1,64}")
KINDS = ("decision", "fact", "preference", "procedure", "lesson", "constraint")
OLD_KINDS = ("decision", "fact", "preference", "procedure")  # the pre-v2 CHECK: no lesson/constraint

SCOPE_SQL = """
CREATE TABLE scope (id INTEGER PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('git','dir','global')));
"""

KNOWLEDGE_TABLE = """CREATE TABLE knowledge (
  id INTEGER PRIMARY KEY,
  scope_id INTEGER NOT NULL REFERENCES scope(id),
  kind TEXT NOT NULL CHECK (kind IN @KINDS@),
  text TEXT,
  status TEXT NOT NULL
    CHECK (status IN ('current','superseded','retracted','erased')),
  supersedes INTEGER REFERENCES knowledge(id),
  superseded_by INTEGER REFERENCES knowledge(id),
  retract_reason TEXT,
  actor TEXT NOT NULL,
  created_at REAL NOT NULL,
  confidence TEXT
    CHECK (confidence IS NULL OR confidence IN
      ('observed','reported','inferred')),
  valid_until REAL,
  sensitivity TEXT NOT NULL DEFAULT 'normal'
    CHECK (sensitivity IN ('normal','restricted')),
  contradicts INTEGER REFERENCES knowledge(id),
  tags TEXT,
  CHECK (status = 'erased' OR text IS NOT NULL))"""

FTS_SQL = """
CREATE VIRTUAL TABLE knowledge_fts USING fts5(text,
  content='knowledge', content_rowid='id');
INSERT INTO knowledge_fts(knowledge_fts, rank) VALUES ('secure-delete', 1);
"""

TRIGGERS = {
    "knowledge_ai": """
CREATE TRIGGER knowledge_ai AFTER INSERT ON knowledge BEGIN
  INSERT INTO knowledge_fts(rowid, text)
    SELECT new.id, new.text WHERE new.text IS NOT NULL; END""",
    "knowledge_ad": """
CREATE TRIGGER knowledge_ad AFTER DELETE ON knowledge BEGIN
  INSERT INTO knowledge_fts(knowledge_fts, rowid, text)
    SELECT 'delete', old.id, old.text WHERE old.text IS NOT NULL; END""",
    "knowledge_au": """
CREATE TRIGGER knowledge_au AFTER UPDATE ON knowledge BEGIN
  INSERT INTO knowledge_fts(knowledge_fts, rowid, text)
    SELECT 'delete', old.id, old.text WHERE old.text IS NOT NULL;
  INSERT INTO knowledge_fts(rowid, text)
    SELECT new.id, new.text WHERE new.text IS NOT NULL; END""",
}

CITATION_SQL = """
CREATE TABLE citation (id INTEGER PRIMARY KEY,
  knowledge_id INTEGER NOT NULL REFERENCES knowledge(id),
  provider TEXT NOT NULL, thread_id TEXT NOT NULL,
  line INTEGER NOT NULL, part INTEGER NOT NULL,
  line_sha256 TEXT NOT NULL,
  role TEXT NOT NULL, kind TEXT NOT NULL, ts TEXT,
  quote TEXT, span_start INTEGER, span_end INTEGER,
  state TEXT NOT NULL DEFAULT 'live' CHECK (state IN ('live','erased')));
CREATE INDEX citation_target ON citation(provider, thread_id, line, part);
"""

LOG_SQL = """
CREATE TABLE knowledge_log (id INTEGER PRIMARY KEY,
  knowledge_id INTEGER NOT NULL,
  action TEXT NOT NULL CHECK (action IN
    ('add','supersede','superseded','retract','erase')),
  actor TEXT NOT NULL, at REAL NOT NULL);
CREATE TRIGGER knowledge_log_no_update BEFORE UPDATE ON knowledge_log BEGIN
  SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER knowledge_log_no_delete BEFORE DELETE ON knowledge_log BEGIN
  SELECT RAISE(ABORT, 'append-only'); END;
"""


def db_path(home: Path | str) -> Path:
    """Return the store file under a data home."""
    return Path(home) / DB_NAME


def create(
    home: Path | str,
    *,
    user_version: int = 2,
    drop_triggers: tuple[str, ...] = (),
    fts: bool = True,
    old_kind: bool = False,
    drop_column: str | None = None,
) -> Path:
    """Create a store; the keyword switches build the broken variants the negative controls need.

    `drop_column` drops one typed column after creation, `fts=False` omits knowledge_fts and its triggers,
    `old_kind` keeps the typed columns but uses the pre-v2 kind CHECK.
    """
    path = db_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    kinds = OLD_KINDS if old_kind else KINDS
    table = KNOWLEDGE_TABLE.replace("@KINDS@", str(kinds))
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(SCOPE_SQL + table + ";\n" + CITATION_SQL + LOG_SQL)
        if fts:
            conn.executescript(FTS_SQL)
            for name, ddl in TRIGGERS.items():
                if name not in drop_triggers:
                    conn.execute(ddl)
        if drop_column:
            conn.execute(f"ALTER TABLE knowledge DROP COLUMN {drop_column}")  # sqlite >= 3.35
        conn.execute(f"PRAGMA user_version={int(user_version)}")
        conn.commit()
    finally:
        conn.close()
    return path


def collapse(text: str) -> str:
    """Whitespace-collapse like Muninn's quote handling."""
    return " ".join(text.split())


def load_events(roots: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    """Read synthetic Claude transcripts (<claude-projects>/**/<session>.jsonl) into events keyed by session id.

    user text is a prompt, assistant text a reply, assistant tool_use a tool call. A path under
    `subagents` is not a primary thread, so its events are not citable.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    base = roots.get("claude-projects")
    if not base:
        return out
    for f in sorted(Path(base).rglob("*.jsonl")):
        sess = f.stem
        evs: list[dict[str, Any]] = []
        primary = "subagents" not in f.parts
        for line, raw in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            try:
                obj: dict[str, Any] = json.loads(raw)
            except ValueError:
                continue
            msg: dict[str, Any] = obj.get("message") or {}
            content: Any = msg.get("content")
            blocks: list[dict[str, Any]] = (
                [{"type": "text", "text": content}] if isinstance(content, str) else list(content or [])
            )
            part = 0
            for b in blocks:
                if obj.get("type") == "user" and b.get("type") == "text":
                    role, kind, text = "user", "prompt", b.get("text", "")
                elif obj.get("type") == "assistant" and b.get("type") == "text":
                    role, kind, text = "assistant", "reply", b.get("text", "")
                elif obj.get("type") == "assistant" and b.get("type") == "tool_use":
                    role, kind, text = "assistant", "tool_call", json.dumps(b.get("input", {}))
                else:
                    continue
                part += 1
                evs.append(
                    {
                        "thread": sess,
                        "line": line,
                        "part": part,
                        "role": role,
                        "kind": kind,
                        "text": text,
                        "primary": primary,
                        "ts": obj.get("timestamp"),
                        "sha": hashlib.sha256(raw.encode()).hexdigest(),
                    }
                )
        out.setdefault(sess, []).extend(evs)
    return out


def roots_from_env() -> dict[str, str]:
    """Parse MUNINN_ROOTS (a JSON object) the way Muninn does."""
    raw = os.environ.get("MUNINN_ROOTS")
    return {k: str(v) for k, v in json.loads(raw).items()} if raw else {}


class RefusedError(Exception):
    """A refused write; `code` goes out as {"error": code} with rc 2."""


def kid_of(value: object) -> int | None:
    """Parse 12, '12' or 'K12' to an id."""
    m = re.fullmatch(r"[Kk]?([0-9]{1,18})", str(value or "").strip())
    return int(m[1]) or None if m else None


def check_citation(events: dict[str, list[dict[str, Any]]], ref: str, quote: str) -> dict[str, Any]:
    """Same rules as Muninn check_citation: resolve, citable, 12..300 chars, verbatim, short only as a whole prompt."""
    m = re.fullmatch(r"claude:(.+):(\d+)\.(\d+)", ref)
    if not m:
        raise RefusedError("not_found")
    sess, line, part = m[1], int(m[2]), int(m[3])
    ev = next((e for e in events.get(sess, []) if (e["line"], e["part"]) == (line, part)), None)
    if ev is None:
        raise RefusedError("not_found")
    if not ev["primary"]:
        raise RefusedError("not_citable")
    wanted = collapse(quote)
    if not wanted or len(wanted) > QUOTE_MAX:
        raise RefusedError("quote_length")
    text = collapse(ev["text"])
    if wanted not in text:
        raise RefusedError("quote_not_found")
    short = len(wanted) < QUOTE_MIN
    if short and not ((ev["role"], ev["kind"]) == ("user", "prompt") and text == wanted):
        raise RefusedError("quote_length")
    start = text.index(wanted)
    return {**ev, "quote": wanted, "span": (start, start + len(wanted)), "approval": short}


def require_proposals(events: dict[str, list[dict[str, Any]]], cites: list[dict[str, Any]]) -> None:
    """An approval needs the reply right before it cited too (ONLY this rule makes 'yes' acceptable)."""
    cited = {(c["thread"], c["line"], c["part"]) for c in cites}
    for c in cites:
        if not c["approval"]:
            continue
        before = [
            e for e in events[c["thread"]] if e["kind"] == "reply" and (e["line"], e["part"]) < (c["line"], c["part"])
        ]
        if not before or (c["thread"], before[-1]["line"], before[-1]["part"]) not in cited:
            raise RefusedError("approval_needs_reply")


def parse_add(argv: list[str]) -> dict[str, Any]:
    """Parse `know add` flags (ordered --cite/--quote pairs, repeated --tag)."""
    a: dict[str, Any] = {"cites": [], "tags": [], "alone": [], "global": False, "sensitivity": "normal"}
    pending: str | None = None
    flags = {
        "--kind": "kind",
        "--text": "text",
        "--supersedes": "supersedes",
        "--confidence": "confidence",
        "--valid-until": "valid_until",
        "--sensitivity": "sensitivity",
        "--contradicts": "contradicts",
        "--scope-loop": "loop",
    }
    i = 0
    while i < len(argv):
        f = argv[i]
        if i + 1 == len(argv) and f != "--global":
            raise RefusedError("bad_usage")
        if f == "--global":
            a["global"] = True
        elif f == "--cite":
            i += 1
            pending = argv[i]
        elif f == "--quote":
            i += 1
            if pending is not None:
                a["cites"].append((pending, argv[i]))
                pending = None
            else:
                a["alone"].append(argv[i])
        elif f == "--tag":
            i += 1
            a["tags"].append(argv[i])
        elif f in flags:
            i += 1
            a[flags[f]] = argv[i]
        else:
            raise RefusedError("bad_usage")
        i += 1
    if pending is not None or len(a["alone"]) > 1 or "kind" not in a or "text" not in a:
        raise RefusedError("bad_usage")
    return a


def validate_typed(a: dict[str, Any], now: float) -> float | None:
    """Typed-field checks in Muninn's order; returns valid_until epoch."""
    if a.get("confidence") not in (None, "observed", "reported", "inferred"):
        raise RefusedError("bad_confidence")
    if a["sensitivity"] not in ("normal", "restricted"):
        raise RefusedError("bad_sensitivity")
    if len(a["tags"]) > 10 or not all(TAG.fullmatch(t) for t in a["tags"]):
        raise RefusedError("bad_tags")
    loop = a.get("loop")
    if loop is not None and (a["global"] or not LOOP.fullmatch(loop)):
        raise RefusedError("bad_loop_scope")
    if a.get("contradicts") is not None and kid_of(a["contradicts"]) is None:
        raise RefusedError("bad_contradicts")
    if a.get("valid_until") is None:
        return None
    try:
        dt = datetime.datetime.fromisoformat(a["valid_until"].strip())
    except ValueError:
        raise RefusedError("bad_valid_until") from None
    at = dt.replace(tzinfo=dt.tzinfo or datetime.timezone.utc).timestamp()
    if at <= now:
        raise RefusedError("bad_valid_until")
    return at
