#!/usr/bin/env python3
"""Hermetic fake `muninn` CLI over a real sqlite3 schema-v2 file (test infrastructure only).

Honours MUNINN_HOME (store dir) and MUNINN_ROOTS (JSON map; `claude-projects` holds synthetic Claude transcripts) and
resolves refs like claude:<session>:<line>.<part>. Implements `know add|list|show|retract`, `search --all-projects`
(knowledge section), `session <root>`, `doctor` and `--version` (stale 0.1.0, overridable with FAKE_MUNINN_VERSION).
Refusals are stdout JSON {"error": code} with rc 2, using the same rules as Muninn's knowledge_cite.py.
FAKE_MUNINN_HELP=real makes `--help` behave like the live binary (usage on stderr, rc 2); the default prints it on
stdout with rc 0, which is what the adapter's probe expects.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.tests import fake_muninn_store as fs  # noqa: E402
from scripts.tests.fake_muninn_read import (
    cmd_list,
    cmd_retract,
    cmd_search,
    cmd_show,
    connect,
    entry,
    out,
)  # noqa: E402
from scripts.tests.fake_muninn_store import (  # noqa: E402
    RefusedError,
    check_citation,
    kid_of,
    parse_add,
    require_proposals,
    validate_typed,
)

ADD_HELP = (
    "usage: know add --kind {decision,fact,preference,procedure,lesson,constraint}"
    " --scope-loop --confidence --valid-until --sensitivity --contradicts --tag"
)
LIST_HELP = "usage: know list --status --kind --tag --all-projects --scope-loop"
CALLER_ENV = ("CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID", "CODEX_THREAD_ID")


def scope_id(conn: sqlite3.Connection, key: str, kind: str) -> int:
    """Find or create a scope row."""
    row = conn.execute("SELECT id FROM scope WHERE key = ?", (key,)).fetchone()
    if row:
        return int(row[0])
    return int(conn.execute("INSERT INTO scope(key, label, kind) VALUES (?, ?, ?)", (key, key, kind)).lastrowid or 0)


def gather_cites(a: dict[str, Any], events: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Check every --cite/--quote pair and the optional bare --quote (the caller session's own prompt)."""
    found = [check_citation(events, ref, q) for ref, q in a["cites"]]
    if a["alone"]:
        sess = next((os.environ[n] for n in CALLER_ENV if os.environ.get(n)), None)
        if sess is None:
            raise RefusedError("no_caller_session")
        wanted = fs.collapse(a["alone"][0])
        if not wanted or len(wanted) > fs.QUOTE_MAX:
            raise RefusedError("quote_length")
        for e in reversed([e for e in events.get(sess, []) if e["kind"] == "prompt" and e["role"] == "user"]):
            try:
                found.append(check_citation(events, f"claude:{sess}:{e['line']}.{e['part']}", a["alone"][0]))
                break
            except RefusedError:
                continue
        else:
            raise RefusedError("quote_not_found")
    return list({(c["thread"], c["line"], c["part"], c["quote"]): c for c in found}.values())


def write_entry(conn: sqlite3.Connection, a: dict[str, Any], found: list[dict[str, Any]], until: float | None) -> int:
    """Insert the entry, its citations and log rows (caller holds the transaction); return the new id."""
    now = time.time()
    loop = a.get("loop")
    if loop is not None:
        sid = scope_id(conn, f"loop:{loop}", "dir")
    elif a["global"]:
        sid = scope_id(conn, "global", "global")
    else:
        sid = scope_id(conn, os.path.realpath(os.getcwd()), "dir")
    old = None
    if a.get("supersedes") is not None:
        old = kid_of(a["supersedes"])
        q = "SELECT scope_id, status FROM knowledge WHERE id = ?"
        row = conn.execute(q, (old,)).fetchone() if old else None
        if row is None or row["status"] != "current" or row["scope_id"] != sid:
            raise RefusedError("bad_supersedes")
    link = kid_of(a["contradicts"]) if a.get("contradicts") is not None else None
    if link and conn.execute("SELECT 1 FROM knowledge WHERE id = ?", (link,)).fetchone() is None:
        raise RefusedError("bad_contradicts")
    actor = "claude:" + (os.environ.get("CLAUDE_CODE_SESSION_ID", "user")[:12])
    tags = ",".join(sorted(set(a["tags"]))) or None
    kid = conn.execute(
        "INSERT INTO knowledge(scope_id, kind, text, status, supersedes, actor, created_at, confidence,"
        " valid_until, sensitivity, contradicts, tags) VALUES (?, ?, ?, 'current', ?, ?, ?, ?, ?, ?, ?, ?)",
        (sid, a["kind"], a["text"].strip(), old, actor, now, a.get("confidence"), until, a["sensitivity"], link, tags),
    ).lastrowid
    conn.executemany(
        "INSERT INTO citation(knowledge_id, provider, thread_id, line, part, line_sha256, role, kind, ts,"
        " quote, span_start, span_end) VALUES (?, 'claude', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (kid, c["thread"], c["line"], c["part"], c["sha"], c["role"], c["kind"], c["ts"], c["quote"], *c["span"])
            for c in found
        ],
    )
    logged = [(kid, "add")]
    if old is not None:
        conn.execute("UPDATE knowledge SET status = 'superseded', superseded_by = ? WHERE id = ?", (kid, old))
        logged += [(kid, "supersede"), (old, "superseded")]
    conn.executemany(
        "INSERT INTO knowledge_log(knowledge_id, action, actor, at) VALUES (?, ?, ?, ?)",
        [(k, act, actor, now) for k, act in logged],
    )
    return int(kid or 0)


def cmd_add(home: Path, argv: list[str]) -> int:
    """`know add`: validate, cite-check, then write entry + citations + log rows in one transaction."""
    try:
        a = parse_add(argv)
        if a["kind"] not in fs.KINDS:
            raise RefusedError("bad_kind")
        if not 1 <= len(a["text"].strip()) <= 500:
            raise RefusedError("text_length")
        until = validate_typed(a, time.time())
        if not a["cites"] and not a["alone"]:
            raise RefusedError("uncited")
        events = fs.load_events(fs.roots_from_env())
        found = gather_cites(a, events)
        require_proposals(events, found)
        if a["kind"] == "preference" and not any((c["role"], c["kind"]) == ("user", "prompt") for c in found):
            raise RefusedError("preference_needs_user")
        conn = connect(home)
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                kid = write_entry(conn, a, found, until)
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            return out({"entry": entry(conn, kid)})
        finally:
            conn.close()
    except RefusedError as r:
        return out({"error": str(r)}, 2)
    except sqlite3.IntegrityError:
        return out({"error": "store_constraint"}, 1)  # e.g. a pre-v2 kind CHECK rejecting lesson/constraint


def main(argv: list[str]) -> int:
    """Dispatch like the real CLI."""
    home = Path(os.environ.get("MUNINN_HOME") or Path.home() / ".local/share/muninn")
    if "--help" in argv or "-h" in argv:
        text = (
            ADD_HELP if argv[:2] == ["know", "add"] else LIST_HELP if argv[:2] == ["know", "list"] else "usage: muninn"
        )
        if os.environ.get("FAKE_MUNINN_HELP") == "real":
            sys.stderr.write(text + "\n")
            return 2
        print(text)
        return 0
    if argv == ["--version"]:
        print("muninn " + os.environ.get("FAKE_MUNINN_VERSION", "0.1.0"))
        return 0
    cmd, rest = (argv[0] if argv else ""), argv[1:]
    if cmd == "know" and rest:
        sub, args = rest[0], rest[1:]
        if sub == "add":
            return cmd_add(home, args)
        if sub == "list":
            return cmd_list(home, args)
        if sub == "show" and args:
            return cmd_show(home, args[0])
        if sub == "retract" and args:
            return cmd_retract(home, args)
    elif cmd == "search":
        return cmd_search(home, rest)
    elif cmd == "session" and rest:
        evs = fs.load_events(fs.roots_from_env()).get(rest[0], [])
        return out(
            {
                "session": rest[0],
                "events": [
                    {
                        "ref": f"claude:{e['thread']}:{e['line']}.{e['part']}",
                        "role": e["role"],
                        "kind": e["kind"],
                        "text": e["text"],
                    }
                    for e in evs
                ],
            }
        )
    elif cmd == "doctor":
        conn = connect(home)
        try:
            return out({"ok": True, "user_version": conn.execute("PRAGMA user_version").fetchone()[0]})
        finally:
            conn.close()
    sys.stderr.write("usage: muninn ...\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
