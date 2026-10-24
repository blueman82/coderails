"""Read side of the fake `muninn` CLI: entry rendering, `know list/show/retract` and `search` (test infrastructure)."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from scripts.tests import fake_muninn_store as fs
from scripts.tests.fake_muninn_store import kid_of

LIVE = "(k.valid_until IS NULL OR k.valid_until > ?)"


def out(obj: dict[str, Any], rc: int = 0) -> int:
    """Print the JSON answer and return the exit code."""
    print(json.dumps(obj))
    return rc


def stamp(at: float | None) -> str | None:
    """UTC ISO timestamp of epoch seconds."""
    return None if at is None else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at))


def connect(home: Path) -> sqlite3.Connection:
    """Open the store, creating a fresh v2 one when none exists yet (as Muninn does)."""
    if not fs.db_path(home).exists():
        fs.create(home)
    conn = sqlite3.connect(str(fs.db_path(home)), isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def entry(conn: sqlite3.Connection, kid: int) -> dict[str, Any]:
    """Render one entry the way `know list/show` does."""
    r = conn.execute(
        "SELECT k.*, s.label FROM knowledge k JOIN scope s ON s.id = k.scope_id WHERE k.id = ?", (kid,)
    ).fetchone()
    cites = conn.execute("SELECT * FROM citation WHERE knowledge_id = ? ORDER BY id", (kid,)).fetchall()
    keys = r.keys()
    vu = r["valid_until"] if "valid_until" in keys else None
    return {
        "id": f"K{r['id']}",
        "kind": r["kind"],
        "text": r["text"],
        "status": r["status"],
        "scope": r["label"],
        "actor": r["actor"],
        "date": time.strftime("%Y-%m-%d", time.gmtime(r["created_at"])),
        "supersedes": f"K{r['supersedes']}" if r["supersedes"] else None,
        "superseded_by": f"K{r['superseded_by']}" if r["superseded_by"] else None,
        "confidence": r["confidence"],
        "valid_until": stamp(vu),
        "expired": r["status"] == "current" and vu is not None and vu <= time.time(),
        "sensitivity": r["sensitivity"],
        "contradicts": f"K{r['contradicts']}" if r["contradicts"] else None,
        "tags": r["tags"].split(",") if r["tags"] else [],
        "cites": [
            {
                "ref": f"{c['provider']}:{c['thread_id']}:{c['line']}.{c['part']}",
                "role": c["role"],
                "kind": c["kind"],
                "ts": c["ts"],
                "quote": c["quote"],
                "span": [c["span_start"], c["span_end"]],
                "state": c["state"],
                "verify": "ok",
            }
            for c in cites
        ],
    }


def cmd_list(home: Path, argv: list[str]) -> int:
    """`know list`: --status/--kind/--tag/--all-projects/--scope-loop."""
    status, everywhere = "current", False
    kind: str | None = None
    loop: str | None = None
    tags: list[str] = []
    i = 0
    while i < len(argv):
        f = argv[i]
        if f == "--all-projects":
            everywhere = True
        else:
            i += 1
            if f == "--status":
                status = argv[i]
            elif f == "--kind":
                kind = argv[i]
            elif f == "--tag":
                tags.append(argv[i])
            elif f == "--scope-loop":
                loop = argv[i]
        i += 1
    conn = connect(home)
    try:
        where: list[str] = ["1"]
        args: list[Any] = []
        if status == "expired":
            where.append(f"k.status = 'current' AND NOT {LIVE}")
            args.append(time.time())
        elif status != "all":
            where.append("k.status = ?")
            args.append(status)
            if status == "current":
                where.append(LIVE)
                args.append(time.time())
        for t in sorted(set(tags)):
            where.append("instr(',' || k.tags || ',', ?) > 0")
            args.append(f",{t},")
        if kind:
            where.append("k.kind = ?")
            args.append(kind)
        if loop is not None:
            sid = conn.execute("SELECT id FROM scope WHERE key = ?", (f"loop:{loop}",)).fetchone()
            where.append("k.scope_id = ?")
            args.append(sid[0] if sid else 0)
        elif not everywhere:
            where.append("k.scope_id IN (SELECT id FROM scope WHERE key IN (?, 'global'))")
            args.append(os.path.realpath(os.getcwd()))
        rows = conn.execute(
            f"SELECT k.id FROM knowledge k WHERE {' AND '.join(where)} ORDER BY k.created_at DESC, k.id DESC", args
        )
        entries = [entry(conn, r["id"]) for r in rows.fetchall()]
        return out({"count": len(entries), "entries": entries})
    finally:
        conn.close()


def cmd_show(home: Path, kid_arg: str) -> int:
    """`know show K`: entry, supersede chain and log."""
    conn = connect(home)
    try:
        kid = kid_of(kid_arg)
        if kid is None or conn.execute("SELECT 1 FROM knowledge WHERE id = ?", (kid,)).fetchone() is None:
            return out({"error": "not_found"}, 2)

        def chain(col: str) -> list[dict[str, Any]]:
            res: list[dict[str, Any]] = []
            seen, nxt = {kid}, conn.execute(f"SELECT {col} FROM knowledge WHERE id = ?", (kid,)).fetchone()[0]
            while nxt and nxt not in seen:
                seen.add(nxt)
                r = conn.execute(f"SELECT *, {col} AS step FROM knowledge WHERE id = ?", (nxt,)).fetchone()
                res.append({"id": f"K{r['id']}", "kind": r["kind"], "text": r["text"], "status": r["status"]})
                nxt = r["step"]
            return res

        log = [
            {"action": r["action"], "actor": r["actor"], "at": stamp(r["at"])}
            for r in conn.execute("SELECT * FROM knowledge_log WHERE knowledge_id = ? ORDER BY id", (kid,))
        ]
        return out(
            {
                "entry": entry(conn, kid),
                "chain": {"supersedes": chain("supersedes"), "superseded_by": chain("superseded_by")},
                "log": log,
            }
        )
    finally:
        conn.close()


def cmd_retract(home: Path, argv: list[str]) -> int:
    """`know retract K [--reason R]`."""
    reason = argv[argv.index("--reason") + 1] if "--reason" in argv else ""
    conn = connect(home)
    try:
        kid = kid_of(argv[0])
        row = conn.execute("SELECT status FROM knowledge WHERE id = ?", (kid,)).fetchone() if kid else None
        if row is None:
            return out({"error": "not_found"}, 2)
        if row["status"] != "current":
            return out({"error": "not_current"}, 2)
        conn.execute(
            "UPDATE knowledge SET status = 'retracted', retract_reason = ? WHERE id = ?", (reason or None, kid)
        )
        conn.execute(
            "INSERT INTO knowledge_log(knowledge_id, action, actor, at) VALUES (?, 'retract', 'user', ?)",
            (kid, time.time()),
        )
        return out({"entry": entry(conn, int(kid or 0))})
    finally:
        conn.close()


def cmd_search(home: Path, argv: list[str]) -> int:
    """`search QUERY --all-projects`: knowledge section from knowledge_fts (current, non-expired entries)."""
    words = re.findall(r"\w+", argv[0]) if argv else []
    conn = connect(home)
    try:
        hits: list[dict[str, Any]] = []
        if words:
            fts = " OR ".join(f'"{w}"' for w in words)
            rows = conn.execute(
                "SELECT k.id FROM knowledge_fts JOIN knowledge k ON k.id = knowledge_fts.rowid"
                f" WHERE knowledge_fts MATCH ? AND k.status = 'current' AND {LIVE} ORDER BY bm25(knowledge_fts), k.id",
                (fts, time.time()),
            ).fetchall()
            hits = [
                {k: e[k] for k in ("id", "kind", "text", "sensitivity", "tags")}
                | {"cites": [c["ref"] for c in e["cites"]]}
                for e in (entry(conn, r["id"]) for r in rows)
            ]
        return out({"hits": [], "knowledge": hits})
    finally:
        conn.close()
