#!/usr/bin/env python3
"""One stdio MCP server per role: `capability_mcp.py --role <agent>` serves exactly the tools profiles.json grants it.

Newline-delimited JSON-RPC (initialize, notifications/initialized, ping, tools/list, tools/call). The role is fixed at
launch and is never a tool argument. Tool calls dispatch in-process to capability.TOOLS; MCP names replace the dot with
an underscore (repo.inspect -> repo_inspect). Every call and refusal appends a fail-open trace row.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import capability as cap  # noqa: E402

ROOT = cap.ROOT
PROTOCOL = "2024-11-05"
ALL_TOOLS = {name.replace(".", "_"): name for name in cap.TOOLS}
STR, INT = {"type": "string"}, {"type": "integer"}
OPS = ["read", "list", "grep", "status", "log", "show", "blame", "wc", "sha256", "glob"]


def schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """An object schema that closes the property set (no `role`) and adds the optional worktree argument."""
    wt = {"worktree": {"type": "string", "description": "Absolute path of a worktree listed by `git worktree list`."}}
    return {"type": "object", "properties": {**props, **wt}, "required": required, "additionalProperties": False}


SCHEMAS = {
    "repo.inspect": schema(
        {
            "op": {"type": "string", "enum": OPS},
            "path": STR,
            "pattern": STR,
            "spec": {**STR, "description": "<ref>:<path> for op=show"},
            "max_bytes": INT,
            "offset": INT,
            "max_results": INT,
            "n": INT,
        },
        ["op"],
    ),
    "diff.read": schema(
        {"base": STR, "head": STR, "paths": {"type": "array", "items": STR}, "max_bytes": INT}, ["base"]
    ),
    "tests.run": schema({"name": STR, "timeout_s": INT}, ["name"]),
    "pr.comment": schema({"pr": INT, "body": STR}, ["pr", "body"]),
    "cmd.run": schema({"name": STR, "args": {"type": "object", "additionalProperties": STR}}, ["name"]),
}


def emit(outcome: str, code: str, tool: str, role: str) -> bool:
    """Append one fail-open trace row {tool, role, via: mcp}; False if the trace library or disk failed."""
    ids = ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID")
    session = next((os.environ[k] for k in ids if os.environ.get(k)), "unattributed")
    try:
        module = importlib.import_module("hooks.scripts.lib.trace_row")
    except ImportError:
        return False
    inputs = {"tool": tool, "role": role, "via": "mcp"}
    return bool(module.append_row("capability", outcome, code, session, inputs=inputs))


def refuse_start(role: str, reason: str) -> int:
    """Startup refusal: reason on stderr, a capability_mcp_refused row, exit 2."""
    print(f"capability_mcp: {reason}", file=sys.stderr)
    emit("refused", "capability_mcp_refused", "startup", role)
    return 2


def envelope(tool: str, now: str, traced: bool, **fields: object) -> dict[str, object]:
    """The typed envelope shared with capability.py's CLI."""
    return {"tool": tool, "ts": now, "traced": traced, **fields}


def call(role: str, allowed: dict[str, str], raw: object) -> tuple[Any, Any]:
    """tools/call: (result, error). A name outside `allowed` is a JSON-RPC error and nothing is dispatched."""
    params = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
    name = str(params["name"]) if isinstance(params.get("name"), str) else ""
    tool = allowed.get(name)
    if tool is None:
        emit("refused", "capability_wrong_role", name[:40], role)
        return None, {"code": -32602, "message": f"tool {name[:40]!r} is not available to this role"}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        status, result, evidence = cap.TOOLS[tool](params.get("arguments", {}))
    except (cap.RefusalError, OSError, subprocess.SubprocessError) as error:
        code = error.code if isinstance(error, cap.RefusalError) else "capability_io_error"
        detail = error.detail if isinstance(error, cap.RefusalError) else str(getattr(error, "strerror", "") or "")
        traced = emit("refused", code, tool, role)
        body = envelope(tool, now, traced, ok=False, exit_status=2, refusal=code, detail=detail)
        return {"content": [{"type": "text", "text": json.dumps(body)}], "isError": True}, None
    sha = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    traced = emit("ok", tool, tool, role)
    body = envelope(tool, now, traced, ok=True, exit_status=status, artifact_sha=sha, evidence=evidence, result=result)
    return {"content": [{"type": "text", "text": json.dumps(body)}], "isError": False}, None


def handle(role: str, allowed: dict[str, str], method: object, params: object) -> tuple[Any, Any]:
    """Route one request to (result, error)."""
    if method == "initialize":
        asked = cast("dict[str, Any]", params).get("protocolVersion") if isinstance(params, dict) else None
        info = {"name": f"coderails-capability-{role}", "version": "1"}
        version = asked if isinstance(asked, str) else PROTOCOL
        return {"protocolVersion": version, "capabilities": {"tools": {}}, "serverInfo": info}, None
    if method == "ping":
        return {}, None
    if method == "tools/list":
        tools = [
            {"name": n, "description": (cap.TOOLS[t].__doc__ or t).strip().splitlines()[0], "inputSchema": SCHEMAS[t]}
            for n, t in sorted(allowed.items())
        ]
        return {"tools": tools}, None
    if method == "tools/call":
        return call(role, allowed, params)
    return None, {"code": -32601, "message": "method not found"}


def serve(role: str, allowed: dict[str, str]) -> int:
    """Read requests from stdin until EOF; notifications (no id) get no reply."""
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            parsed = None
        msg = cast("dict[str, Any]", parsed)
        if not isinstance(parsed, dict):
            reply: dict[str, Any] = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        elif "id" not in msg:
            continue
        else:
            result, error = handle(role, allowed, msg.get("method"), msg.get("params"))
            reply = {"jsonrpc": "2.0", "id": msg["id"], **({"error": error} if error else {"result": result})}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()
    return 0


def main(argv: list[str]) -> int:
    """Validate `--role <agent>` against profiles.json, then serve exactly that role's tools."""
    if len(argv) != 2 or argv[0] != "--role":
        return refuse_start("?", "usage: capability_mcp.py --role <agent>")
    role = argv[1]
    try:
        profile = json.loads((ROOT / "capabilities" / "profiles.json").read_text(encoding="utf-8"))
        if role not in profile["agents"]:
            return refuse_start(role, f"role {role!r} is not in capabilities/profiles.json")
        granted = profile["agents"][role]
    except (OSError, ValueError, KeyError, TypeError):
        return refuse_start(role, "capabilities/profiles.json unreadable or malformed")
    allowed = {name: tool for name, tool in ALL_TOOLS.items() if tool in granted}
    if not allowed:
        return refuse_start(role, f"role {role!r} holds no capability tool")
    return serve(role, allowed)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
