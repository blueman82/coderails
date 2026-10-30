"""Launch Codex with the current OAuth login and parse its terminal result."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, cast

import worker_status

PASS_ENV = ("PATH", "HOME", "CODEX_HOME", "TMPDIR", "LANG", "LC_ALL", "TERM")

MODELS = {"fast-mechanical": "gpt-6-luna", "default": "gpt-6.1-sol", "frontier": "gpt-6-astra"}

SCHEMA = {
    "type": "object",
    "properties": {
        "outcome": {"type": "string", "enum": ["done", "skipped", "failed", *worker_status.STATUSES]},
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


def guarded_role(root: Path, role: str) -> bool:
    """Require policy and the installed shell-off role contract to select the same route."""
    if re.fullmatch(r"[a-z][a-z0-9-]{0,60}", role) is None:
        raise ValueError("driver role capability policy has an invalid role")
    try:
        raw: object = json.loads((root / "capabilities/profiles.json").read_text())["agents"][role]
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in cast(list[object], raw)):
            raise ValueError("capability grants must be a list of strings")
        capabilities = set(cast(list[str], raw))
        contract = (root / "agents" / f"{role}.toml").read_text()
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError("driver role capability profile is invalid") from error
    if not capabilities and role != "spec-reviewer":
        raise ValueError("driver role capability policy is empty")
    guarded = bool(capabilities & {"repo.inspect", "diff.read", "tests.run", "pr.comment", "cmd.run"}) and not bool(
        capabilities & {"shell.raw", "worktree.write"}
    )
    contract = re.sub(r'(?s)""".*?"""|\'\'\'.*?\'\'\'', '""', contract)
    features = re.search(r"(?ms)^\[features\]\s*\n(.*?)(?=^\[|\Z)", contract)
    shell_off = bool(features and re.search(r"(?m)^shell_tool\s*=\s*false\s*$", features.group(1)))
    if guarded != shell_off:
        raise ValueError("driver role capability policy conflicts with its agent contract")
    return guarded


def command(
    prompt: Path,
    checkout: Path,
    cli: str | None = None,
    *,
    role: str = "loop-worker",
    model_role: str = "default",
) -> tuple[list[str], dict[str, str] | None, Path]:
    """Use the installed OAuth CLI with a fixed sandbox and a result schema."""
    if prompt.is_symlink() or not prompt.is_file() or not checkout.is_dir():
        raise ValueError("Codex prompt or checkout is invalid")
    executable = cli or shutil.which("codex")
    if not executable:
        raise ValueError("codex exec is not installed")
    if model_role not in MODELS:
        raise ValueError("driver model role is invalid")
    artifact = prompt.parent
    schema_path = artifact / "result.schema.json"
    data = json.dumps(SCHEMA, sort_keys=True, separators=(",", ":"))
    if schema_path.exists():
        if schema_path.read_text(encoding="utf-8") != data:
            raise ValueError("Codex result schema changed during an attempt")
    else:
        with schema_path.open("x", encoding="utf-8") as stream:
            stream.write(data)
    root = Path(__file__).resolve().parents[3]
    if guarded_role(root, role):
        wrapper = root / "scripts/codex_role_session.py"
        if not wrapper.is_file():
            raise ValueError("guarded Codex role launcher is missing")
        argv = [
            sys.executable,
            str(wrapper),
            "--role",
            role,
            "--prompt-file",
            str(prompt),
            "--prompt-source",
            "stdin",
            "--cwd",
            str(checkout),
            "--schema",
            str(schema_path),
            "--final",
            str(artifact / "final.json"),
            "--model",
            MODELS[model_role],
        ]
        return argv, {key: os.environ[key] for key in PASS_ENV if key in os.environ}, prompt
    else:
        for directory in (checkout.resolve(), *checkout.resolve().parents):
            if (directory / ".codex").exists():
                raise ValueError("project Codex config can add an unguarded MCP server")
            if (directory / ".git").exists():
                break
        argv = [
            executable,
            "exec",
            "--ignore-user-config",
            "--sandbox",
            "read-only" if role == "spec-reviewer" else "workspace-write",
            "-C",
            str(checkout),
            "-",
        ]
    argv[-1:-1] = [
        "--json",
        "--model",
        MODELS[model_role],
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(artifact / "final.json"),
        "-c",
        "features.multi_agent=false",
        "-c",
        'forced_login_method="chatgpt"',
        "-c",
        'model_provider="openai"',
    ]
    return argv, {key: os.environ[key] for key in PASS_ENV if key in os.environ}, prompt


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
    if not all(isinstance(event, str) for event in events):
        return _failed("invalid_event_stream")
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
        or not isinstance(parsed["outcome"], str)
        or parsed["outcome"] not in {"done", "skipped", "failed", *worker_status.STATUSES}
        or not isinstance(parsed["evidence"], str)
        or not parsed["evidence"].strip()
        or (parsed["outcome"] == "done" and not isinstance(parsed["final_report"], dict))
        or (parsed["outcome"] == "skipped" and parsed["final_report"] is not None)
        or (parsed["final_report"] is not None and not isinstance(parsed["final_report"], dict))
    ):
        return _failed("invalid_final_schema")
    try:
        if json.loads(messages[-1]) != parsed:
            return _failed("final_output_mismatch")
    except ValueError:
        return _failed("invalid_agent_message")
    if parsed["outcome"] in worker_status.STATUSES:
        if parsed["final_report"] is not None:
            return _failed("invalid_worker_status")
        try:
            status = json.loads(parsed["evidence"])
        except ValueError:
            return _failed("invalid_worker_status")
        if worker_status.validate(status) != "ok" or status["status"] != parsed["outcome"]:
            return _failed("invalid_worker_status")
        return cast(dict[str, Any], status)
    return parsed
