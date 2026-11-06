"""Small test double for Muninn's request, receipt and current-note CLI contract."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, cast

from scripts.tests import fake_muninn_store as fs


def _path(home: Path) -> Path:
    return home / "requests.json"


def _load(home: Path) -> dict[str, Any]:
    path = _path(home)
    return json.loads(path.read_text()) if path.exists() else {"requests": {}, "knowledge": {}}


def _save(home: Path, data: dict[str, Any]) -> None:
    home.mkdir(parents=True, exist_ok=True)
    _path(home).write_text(json.dumps(data, sort_keys=True))


def _id(prefix: str, text: str) -> str:
    return prefix + hashlib.sha256(text.encode()).hexdigest()[:32]


def request(home: Path, args: list[str]) -> tuple[int, dict[str, Any]]:
    """Create a pending request from a source-backed test session."""
    try:
        session = args[args.index("--session") + 1]
        task = args[args.index("--task") + 1]
    except (ValueError, IndexError):
        return 2, {"error": "bad_usage"}
    if not fs.load_events(fs.roots_from_env()).get(session):
        return 2, {"error": "source_unavailable"}
    project = os.path.realpath(os.getcwd())
    data = _load(home)
    rid = _id("R_", f"{session}|{project}|{task}")
    row = data["requests"].setdefault(
        rid,
        {
            "id": rid,
            "schema_version": 1,
            "policy_digest": "a" * 64,
            "current_attempt_id": None,
            "created_at": 1.0,
            "retry_at": None,
            "accepted": True,
            "state": "pending",
            "scope": {"project_id": project, "task": task},
            "window": {
                "source": {"provider": "claude", "thread_id": session},
                "from_line": 1,
                "through_line": 4,
                "boundary_hash": "a" * 64,
            },
            "receipt": None,
        },
    )
    events = fs.load_events(fs.roots_from_env())[session]
    row["window"]["through_line"] = max(e["line"] for e in events)
    row["window"]["boundary_hash"] = max(events, key=lambda e: e["line"])["sha"]
    _save(home, data)
    return 0, _view(row)


def show(home: Path, rid: str) -> tuple[int, dict[str, Any]]:
    """Show the saved request and its receipt."""
    row = _load(home)["requests"].get(rid)
    if row is None:
        return 2, {"error": "request_unavailable"}
    return 0, {
        "request": _view(row),
        "receipt": row["receipt"],
        "attempts": [],
        "calls": [],
        "evidence": row.get("evidence", []),
        "correction_status": "unknown",
        "diagnostics": [],
    }


def complete(home: Path, args: list[str]) -> tuple[int, dict[str, Any]]:
    """Test-only control: finish one request with an exact note or a no-change receipt."""
    rid = args[0]
    data = _load(home)
    row = data["requests"].get(rid)
    if row is None:
        return 2, {"error": "request_unavailable"}
    kind = args[args.index("--kind") + 1] if "--kind" in args else None
    content = args[args.index("--content") + 1] if "--content" in args else None
    previous = cast("dict[str, Any]", row.get("receipt") or {})
    applied = list(cast("list[dict[str, Any]]", previous.get("applied", [])))
    if kind and content:
        evidence = _evidence(row)
        row["evidence"] = [evidence]
        kid = _id("K_", f"{rid}|{kind}|{content}")
        data["knowledge"][kid] = {
            "id": kid,
            "revision": 1,
            "state": "active",
            "body": {
                "form": "note",
                "kind": kind,
                "scope": row["scope"],
                "content": content,
                "conditions": [],
                "evidence_refs": [evidence["id"]],
                "reason": "test fixture",
            },
            "origin": "review",
            "expiry": None,
            "created_at": 1.0,
            "retracted_at": None,
            "retracted_reason": None,
            "schema_version": 1,
            "evidence_sources": [
                {
                    "evidence_id": evidence["id"],
                    "ref": f"claude:{row['window']['source']['thread_id']}:1.1",
                    "line_sha256": evidence["line_sha256"],
                }
            ],
        }
        affected = {"knowledge_id": kid, "revision": 1}
        if affected not in applied:
            applied.append(affected)
    row["state"] = "completed"
    row["current_attempt_id"] = "A_" + "d" * 32
    row["receipt"] = {
        "schema_version": 1,
        "request_id": rid,
        "attempt_id": "A_" + "d" * 32,
        "applied": applied,
        "unresolved_ids": [],
        "committed_at": 1.0,
        "outcome": "completed" if applied else "no_change",
        "no_change_reason": None if applied else "no matching note",
    }
    _save(home, data)
    return 0, row["receipt"]


def list_current(home: Path, task: str) -> tuple[int, dict[str, Any]]:
    """Return active task notes and broad project notes, like Muninn."""
    project = os.path.realpath(os.getcwd())
    notes = [
        note
        for note in _load(home)["knowledge"].values()
        if note["state"] == "active"
        and note["body"]["scope"]["project_id"] == project
        and note["body"]["scope"]["task"] in (None, task)
        and (note.get("expiry") is None or note["expiry"].get("at") is None or note["expiry"]["at"] > time.time())
    ]
    return 0, {"knowledge": [{k: v for k, v in note.items() if k != "evidence_sources"} for note in notes]}


def show_note(home: Path, kid: str) -> tuple[int, dict[str, Any]]:
    """Show a note by ID."""
    row = _load(home)["knowledge"].get(kid)
    return (0, row) if row else (2, {"error": "knowledge_not_found"})


def retract(home: Path, kid: str) -> tuple[int, dict[str, Any]]:
    """Retract a note in the test store."""
    data = _load(home)
    row = data["knowledge"].get(kid)
    if row is None:
        return 2, {"error": "knowledge_not_found"}
    row["state"] = "retracted"
    _save(home, data)
    return 0, row


def _view(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in ("receipt", "evidence")}


def list_requests(home: Path, args: list[str]) -> tuple[int, dict[str, Any]]:
    """Expose the real public metadata listing; it has only an optional state filter."""
    state = args[args.index("--state") + 1] if "--state" in args else None
    return 0, {
        "requests": [_view(row) for row in _load(home)["requests"].values() if state is None or row["state"] == state]
    }


def _evidence(row: dict[str, Any]) -> dict[str, Any]:
    session = row["window"]["source"]["thread_id"]
    event = next(e for e in fs.load_events(fs.roots_from_env())[session] if e["role"] == "user" and e["primary"])
    base = Path(fs.roots_from_env()["claude-projects"])
    path = next(p for p in base.rglob(session + ".jsonl") if "subagents" not in p.parts)
    raw_lines = path.read_bytes().splitlines(keepends=True)
    line_number = int(event["line"])
    selector = {"json_pointer": "/message/content", "start": None, "end": None}
    return {
        "id": _id("E_", str(path) + str(event["line"])),
        "provider": "claude",
        "thread_id": session,
        "session_root": session,
        "line": event["line"],
        "part": event["part"],
        "line_sha256": event["sha"],
        "source_version": "claude-jsonl-v1",
        "projection_version": "selected-text-v1",
        "original_locator": {
            "kind": "jsonl",
            "path": str(path),
            "byte_offset": sum(map(len, raw_lines[: line_number - 1])),
            "byte_length": len(raw_lines[line_number - 1]),
        },
        "selector": selector,
        "selector_digest": hashlib.sha256(
            json.dumps(selector, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest(),
        "evidence_type": "owner_statement",
        "authority": "direct_owner",
        "scope": {**row["scope"], "task": None},
        "excerpt": event["text"],
        "state": "live",
        "selected_at": 1.0,
    }


def physical(home: Path, ref: str, quote: str | None = None) -> tuple[int, dict[str, Any]]:
    """Re-read the selected physical original on every public open call."""
    retained = [
        e
        for row in _load(home)["requests"].values()
        for e in row.get("evidence", [])
        if ref == f"{e['provider']}:{e['thread_id']}:{e['line']}.{e['part']}"
    ]
    if not retained:
        return 2, {"error": "not_found"}
    evidence = retained[0]
    raw = Path(evidence["original_locator"]["path"]).read_bytes().splitlines()[int(evidence["line"]) - 1]
    event = next(
        e
        for e in fs.load_events(fs.roots_from_env())[evidence["thread_id"]]
        if e["line"] == evidence["line"] and e["part"] == evidence["part"]
    )
    if quote is not None:
        return 0, {"match": bool(quote.strip()) and quote in event["text"], "span": [0, len(quote)]}
    return 0, {
        "id": evidence["line"],
        "ref": ref,
        "provenance": {
            "provider": "claude",
            "thread": evidence["thread_id"],
            "session": evidence["session_root"],
            "role": event["role"],
            "kind": event["kind"],
            "line": evidence["line"],
            "part": evidence["part"],
            "line_sha256": evidence["line_sha256"],
            "source_status": "active",
        },
        "hash_ok": hashlib.sha256(raw).hexdigest() == evidence["line_sha256"],
        "answer_citable": event["primary"],
        "flagged": False,
        "redacted": False,
        "truncated": False,
        "text": event["text"],
        "offset": 0,
        "next_offset": None,
        "chars": len(event["text"]),
        "neighbours": [],
    }
