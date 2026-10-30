"""Small test double for Muninn's request, receipt and current-note CLI contract."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

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
    _save(home, data)
    return 0, {key: row[key] for key in ("id", "state", "scope", "window")}


def show(home: Path, rid: str) -> tuple[int, dict[str, Any]]:
    """Show the saved request and its receipt."""
    row = _load(home)["requests"].get(rid)
    if row is None:
        return 2, {"error": "request_unavailable"}
    return 0, {
        "request": {key: row[key] for key in ("id", "state", "scope", "window")},
        "receipt": row["receipt"],
        "attempts": [],
        "calls": [],
        "evidence": [],
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
    applied: list[dict[str, Any]] = []
    if kind and content:
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
                "evidence_refs": ["E_" + "c" * 32],
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
                    "evidence_id": "E_" + "c" * 32,
                    "ref": f"claude:{row['window']['source']['thread_id']}:1.1",
                    "line_sha256": "a" * 64,
                }
            ],
        }
        applied.append({"knowledge_id": kid, "revision": 1})
    row["state"] = "completed"
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
    return 0, {"knowledge": notes}


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
