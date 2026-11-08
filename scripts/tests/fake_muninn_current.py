"""Account-free current Muninn transport with physical JSONL originals."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.lib.dir_lock import acquire_dir_lock, release_dir_lock  # noqa: E402

RID, KID, EID = "R_" + "1" * 32, "K_" + "2" * 32, "E_" + "3" * 32
AID = "A_" + "4" * 32
QUOTE = "Use the bronze queue when the owner approves the release."
CLAIM = "2.5: choose the bronze queue"


def fixture(root: Path, project: Path, task: str = "L1", kind: str = "decision", claim: str = CLAIM) -> dict[str, Any]:
    """Build full public request, receipt, Note and evidence views independently."""
    original = root / "original.jsonl"
    lines: list[dict[str, Any]] = [
        {
            "type": "response_item",
            "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]},
        }
        for text in (QUOTE, "Keep the second support physically unchanged.")
    ]
    original.write_text("".join(json.dumps(line) + "\n" for line in lines))
    hashes = [hashlib.sha256(json.dumps(line).encode()).hexdigest() for line in lines]
    scope = {"project_id": str(project), "task": task}
    window = {
        "source": {"provider": "codex", "thread_id": "s1"},
        "from_line": 1,
        "through_line": 2,
        "boundary_hash": hashes[1],
    }
    request = {
        "schema_version": 1,
        "id": RID,
        "window": window,
        "scope": scope,
        "policy_digest": "a" * 64,
        "state": "completed",
        "current_attempt_id": AID,
        "created_at": 1.0,
        "retry_at": None,
        "accepted": True,
    }
    evidence = _evidence(lines, hashes, original, project)
    refs = [item["id"] for item in evidence]
    note = {
        "schema_version": 1,
        "id": KID,
        "revision": 3,
        "state": "active",
        "body": {
            "form": "note",
            "kind": kind,
            "scope": scope,
            "content": claim,
            "conditions": [],
            "evidence_refs": refs,
            "reason": "The owner chose the queue.",
        },
        "origin": "review",
        "expiry": None,
        "created_at": 2.0,
        "retracted_at": None,
        "retracted_reason": None,
        "evidence_sources": [
            {"evidence_id": e["id"], "ref": f"codex:s1:{e['line']}.1", "line_sha256": e["line_sha256"]}
            for e in evidence
        ],
    }
    receipt = {
        "schema_version": 1,
        "request_id": RID,
        "attempt_id": AID,
        "applied": [{"knowledge_id": KID, "revision": 3}],
        "unresolved_ids": [],
        "committed_at": 3.0,
        "outcome": "completed",
        "no_change_reason": None,
    }
    return {
        "request": request,
        "receipt": receipt,
        "attempts": [],
        "calls": [],
        "evidence": evidence,
        "correction_status": "unknown",
        "diagnostics": [],
        "notes": [note],
        "project": str(project),
    }


def _evidence(lines: list[dict[str, Any]], hashes: list[str], original: Path, project: Path) -> list[dict[str, Any]]:
    """Make complete selected-evidence views for the public model shape."""
    evidence: list[dict[str, Any]] = []
    offset = 0
    for number, (line, digest) in enumerate(zip(lines, hashes), start=1):
        raw = json.dumps(line).encode()
        selector = {"json_pointer": "/payload/content/0/text", "start": None, "end": None}
        evidence.append(
            {
                "id": EID if number == 1 else "E_" + "5" * 32,
                "provider": "codex",
                "thread_id": "s1",
                "session_root": "s1",
                "line": number,
                "part": 1,
                "line_sha256": digest,
                "source_version": "codex-jsonl-v1",
                "projection_version": "selected-text-v1",
                "original_locator": {
                    "kind": "jsonl",
                    "path": str(original),
                    "byte_offset": offset,
                    "byte_length": len(raw) + 1,
                },
                "selector": selector,
                "selector_digest": hashlib.sha256(
                    json.dumps(selector, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
                ).hexdigest(),
                "evidence_type": "owner_statement",
                "authority": "direct_owner",
                "scope": {"project_id": str(project), "task": None},
                "excerpt": line["payload"]["content"][0]["text"],
                "state": "live",
                "selected_at": 1.0,
            }
        )
        offset += len(raw) + 1
    return evidence


def execute(root: Path, args: list[str]) -> tuple[int, dict[str, Any] | str]:
    """Serve only the current public calls used by the consumer under test."""
    data: dict[str, Any] = json.loads((root / "data.json").read_text())
    observed = {"args": args, "cwd": os.getcwd()}
    if args[:2] == ["learn", "request"] and "--help" not in args and data.get("marker_probe"):
        marker = json.loads(Path(data["marker_probe"]).read_text())
        observed["marker_before_submit"] = marker["records"][0]["muninn"]
    with (root / "calls.jsonl").open("a") as stream:
        stream.write(json.dumps(observed) + "\n")
    if not _locks_clear(data):
        return 2, {"error": "graph_lock_held"}
    if "--help" in args:
        return 2, "learn request --session --task; know list --task"
    if os.getcwd() != data["project"]:
        return 2, {"error": "wrong_test_project"}
    if args[:2] == ["learn", "request"]:
        time.sleep(data.get("submit_delay", 0))
        return 0, data["request"]
    if args[:2] == ["learn", "show"] and args[2] in data.get("extra_details", {}):
        return 0, data["extra_details"][args[2]]
    if args[:2] == ["learn", "show"] and args[2] == data["request"]["id"]:
        return 0, {
            k: data[k]
            for k in ("request", "receipt", "attempts", "calls", "evidence", "correction_status", "diagnostics")
        }
    if args in (["learn", "list"], ["learn", "list", "--state", "completed"]):
        return 0, {"requests": data.get("requests", [data["request"]])}
    if args[:2] == ["know", "list"] and "--task" in args and "--all-projects" not in args:
        return 0, {"knowledge": [{k: v for k, v in note.items() if k != "evidence_sources"} for note in data["notes"]]}
    if args[:2] == ["know", "show"]:
        found = [note for note in data["notes"] if note["id"] == args[2]]
        return (0, found[0]) if len(found) == 1 else (2, {"error": "knowledge_not_found"})
    if args[:1] in (["open"], ["quote-check"]):
        found = [e for e in data["evidence"] if f"{e['provider']}:{e['thread_id']}:{e['line']}.{e['part']}" == args[1]]
        if not found:
            return 2, {"error": "not_found"}
        e = found[0]
        raw_line: bytes = (root / "original.jsonl").read_bytes().splitlines()[int(e["line"]) - 1]
        text = json.loads(raw_line)["payload"]["content"][0]["text"]
        if args[0] == "quote-check":
            return 0, {"match": bool(args[2].strip()) and args[2] in text, "span": [0, len(args[2])]}
        return 0, {
            "id": e["line"],
            "ref": args[1],
            "provenance": {
                "provider": e["provider"],
                "thread": e["thread_id"],
                "session": e["session_root"],
                "ts": None,
                "role": "user",
                "kind": "prompt",
                "tag": None,
                "scope": Path(data["project"]).name,
                "cwd": data["project"],
                "root": "codex-sessions",
                "path": "original.jsonl",
                "line": e["line"],
                "part": e["part"],
                "byte_offset": e["original_locator"]["byte_offset"],
                "line_sha256": e["line_sha256"],
                "source_status": "active",
            },
            "answer_citable": True,
            "flagged": False,
            "redacted": False,
            "truncated": False,
            "text": text,
            "offset": 0,
            "next_offset": None,
            "chars": len(text),
            "hash_ok": hashlib.sha256(raw_line).hexdigest() == e["line_sha256"],
            "neighbours": [],
        }
    return 2, {"error": "unsupported_test_call"}


def _locks_clear(data: dict[str, Any]) -> bool:
    for entry in data.get("graph_locks", []):
        path = Path(entry["path"])
        if entry["kind"] == "directory":
            acquired, _ = acquire_dir_lock(path, 1, 0)
            if not acquired:
                return False
            release_dir_lock(path)
        else:
            with path.open("a+") as handle:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return False
    return True


def main() -> int:
    """Execute from an isolated test fixture, never delegate to installed Muninn."""
    code, payload = execute(Path(os.environ["CURRENT_MUNINN_FIXTURE"]), sys.argv[1:])
    print(payload if isinstance(payload, str) else json.dumps(payload))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
