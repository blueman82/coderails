"""Launch Codex with the current OAuth login and parse its terminal result."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, cast

SCHEMA = {
    "type": "object",
    "properties": {
        "outcome": {"type": "string", "enum": ["done", "failed"]},
        "evidence": {"type": "string"},
        "final_report": {
            "type": ["object", "null"],
            "properties": {
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "label": {"type": "string", "enum": ["verified", "inferred", "guess"]},
                            "source": {"type": "string"},
                        },
                        "required": ["text", "label", "source"],
                        "additionalProperties": False,
                    },
                },
                "did_not_verify": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item": {"type": "string"},
                            "tag": {"type": "string", "enum": ["resolved", "unverifiable"]},
                            "reason": {"type": "string"},
                        },
                        "required": ["item", "tag", "reason"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["claims", "did_not_verify"],
            "additionalProperties": False,
        },
    },
    "required": ["outcome", "evidence", "final_report"],
    "additionalProperties": False,
}


def command(prompt: Path, checkout: Path, cli: str | None = None) -> tuple[list[str], None, Path]:
    """Use the installed OAuth CLI with a fixed sandbox and a result schema."""
    if prompt.is_symlink() or not prompt.is_file() or not checkout.is_dir():
        raise ValueError("Codex prompt or checkout is invalid")
    executable = cli or shutil.which("codex")
    if not executable:
        raise ValueError("codex exec is not installed")
    artifact = prompt.parent
    schema_path = artifact / "result.schema.json"
    data = json.dumps(SCHEMA, sort_keys=True, separators=(",", ":"))
    if schema_path.exists():
        if schema_path.read_text(encoding="utf-8") != data:
            raise ValueError("Codex result schema changed during an attempt")
    else:
        with schema_path.open("x", encoding="utf-8") as stream:
            stream.write(data)
    argv = [
        executable,
        "exec",
        "--json",
        "--sandbox",
        "workspace-write",
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(artifact / "final.json"),
        "-c",
        "features.multi_agent=false",
        "-C",
        str(checkout),
        "-",
    ]
    return argv, None, prompt


def _failed(code: str) -> dict[str, str]:
    """Return a coded failed attempt without treating worker prose as truth."""
    return {"outcome": "failed", "evidence": f"codex:{code}"}


def result(output: Path, exit_code: int) -> dict[str, Any]:
    """Accept only a successful JSONL turn and a closed schema response."""
    if exit_code:
        return _failed(f"process_exit_{exit_code}")
    try:
        decoded: list[object] = [
            json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        final: object = json.loads((output.parent / "final.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _failed("invalid_raw_output")
    if not decoded or not all(isinstance(row, dict) for row in decoded):
        return _failed("invalid_event_stream")
    rows = [cast(dict[str, Any], row) for row in decoded]
    events = [row.get("type") for row in rows]
    if (
        events.count("thread.started") != 1
        or events.count("turn.completed") != 1
        or events[-1] != "turn.completed"
        or any(event in {"turn.failed", "error"} for event in events)
    ):
        return _failed("missing_terminal_success")
    if not isinstance(rows[0].get("thread_id"), str) or not rows[0]["thread_id"]:
        return _failed("missing_thread_identity")
    messages: list[str] = []
    for row in rows:
        raw_item: object = row.get("item")
        if not isinstance(raw_item, dict):
            continue
        item = cast(dict[str, Any], raw_item)
        if item.get("type") == "collab_tool_call":
            return _failed("nested_agent_dispatch")
        if row.get("type") == "item.completed" and item.get("type") == "agent_message":
            content: object = item.get("text")
            if not isinstance(content, str):
                return _failed("invalid_agent_message")
            messages.append(content)
    if not messages:
        return _failed("missing_agent_message")
    if not isinstance(final, dict):
        return _failed("invalid_final_schema")
    parsed = cast(dict[str, Any], final)
    if (
        set(parsed) != {"outcome", "evidence", "final_report"}
        or parsed["outcome"] not in {"done", "failed"}
        or not isinstance(parsed["evidence"], str)
        or not parsed["evidence"].strip()
        or (parsed["outcome"] == "done" and not isinstance(parsed["final_report"], dict))
        or (parsed["outcome"] == "failed" and parsed["final_report"] is not None)
    ):
        return _failed("invalid_final_schema")
    try:
        if json.loads(messages[-1]) != parsed:
            return _failed("final_output_mismatch")
    except ValueError:
        return _failed("invalid_agent_message")
    return parsed
