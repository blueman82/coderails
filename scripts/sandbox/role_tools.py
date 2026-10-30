"""Bind guarded Claude driver roles to their single trusted capability server."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from hooks.scripts.lib.capability_profiles import load_profiles
from scripts.lib.capability_validation import claude_errors, guarded, server_id


def role_tools(role: str) -> tuple[str, str]:
    """Use the installed agent's tool allowlist for a driver worker."""
    if re.fullmatch(r"[a-z][a-z0-9-]{0,60}", role) is None:
        raise ValueError("driver role is invalid")
    source = Path(__file__).resolve().parents[2] / "agents" / f"{role}.md"
    if not source.is_file():
        raise ValueError("driver role instructions are missing")
    lines = source.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError("driver role frontmatter is invalid")
    frontmatter = lines[1 : lines.index("---", 1)]
    fields = dict(line.split(":", 1) for line in frontmatter if ":" in line)
    allowed = fields.get("tools", "").strip()
    denied = fields.get("disallowedTools", "").strip()
    if not allowed:
        raise ValueError("driver role has no tool allowlist")
    if "mcp__plugin_coderails_cap-" in allowed:
        denied += ", Bash, Read, Grep, Glob, WebFetch, Write, Edit, NotebookEdit"
    return allowed, ", ".join(part for part in ("Agent", "Task", denied) if part)


def role_isolation(role: str, allowed: str) -> list[str]:
    """Disable built-ins and inherited MCP servers for capability-only roles."""
    root = Path(__file__).resolve().parents[2]
    caps = load_profiles(root)["agents"].get(role, [])
    if not guarded(caps):
        return []
    if claude_errors(role, caps, [tool.strip() for tool in allowed.split(",")]):
        raise ValueError("driver role tools differ from capability profile")
    server = {
        "command": sys.executable,
        "args": [str(root / "scripts/capability_mcp.py"), "--role", role],
    }
    config = {"mcpServers": {f"plugin_coderails_{server_id(role)}": server}}
    name = f"coderails-driver-{role}"
    prompt = (root / "agents" / f"{role}.md").read_text(encoding="utf-8").split("---", 2)[2].strip()
    definition = {
        name: {
            "description": f"Contained {role}",
            "prompt": prompt,
            "tools": [tool.strip() for tool in allowed.split(",") if tool.strip().startswith("mcp__")],
        }
    }
    return [
        "--tools",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        json.dumps(config, sort_keys=True),
        "--agents",
        json.dumps(definition, sort_keys=True),
        "--agent",
        name,
    ]
