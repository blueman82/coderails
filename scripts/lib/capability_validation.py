"""Derive and check the per-role MCP binding: tool names, generated capabilities/mcp.json, agent files, Codex TOMLs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

from hooks.scripts.lib.capability_profiles import TOOLS

PLUGIN = "coderails"
MAX_TOOL_NAME = 64
# Harness-level tools a guarded agent must never hold: a shell, an editor, a fetcher, or a way to start agents.
FORBIDDEN_TOOLS = frozenset(
    {"Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "Agent", "Task", "WebFetch", "WebSearch"}
    | {"Read", "Grep", "Glob"}
)
# Native tools a guarded agent keeps by exception. preflight-scout runs skills (wiki-query may shell out; without Bash
# that step degrades to UNSUPPORTED, it is never handed a shell).
EXTRA_TOOLS = {"preflight-scout": ("Skill",)}
SHELL_TOOL_OFF = "[features]\nshell_tool = false\n"
MCP_PATH = Path("capabilities") / "mcp.json"


def server_id(role: str) -> str:
    """The MCP server id for a role; short enough that the longest full tool name stays under 64 characters."""
    return f"cap-{role}"


def mcp_name(role: str, tool: str) -> str:
    """The API-visible name of a capability tool for a role: dots become underscores (the API forbids dots)."""
    return f"mcp__plugin_{PLUGIN}_{server_id(role)}__{tool.replace('.', '_')}"


def role_tools(caps: list[str]) -> list[str]:
    """The capability tools (not shell.raw / worktree.write) among a role's capabilities."""
    return [cap for cap in TOOLS if cap in caps]


def expected_tools(role: str, caps: list[str]) -> list[str]:
    """Exactly what a guarded agent's frontmatter `tools:` must list."""
    return [mcp_name(role, tool) for tool in role_tools(caps)] + list(EXTRA_TOOLS.get(role, ()))


def guarded(caps: list[str]) -> bool:
    """A guarded agent has a capability tool and neither a raw shell nor a write capability."""
    return bool(role_tools(caps)) and "shell.raw" not in caps and "worktree.write" not in caps


def guarded_roles(profiles: dict[str, Any]) -> list[str]:
    """Guarded roles in profile order."""
    return [name for name, caps in profiles["agents"].items() if guarded(caps)]


def mcp_config(profiles: dict[str, Any]) -> dict[str, Any]:
    """The generated capabilities/mcp.json: one fixed-role server per guarded role."""
    servers = {
        server_id(role): {
            "command": "python3",
            "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/capability_mcp.py", "--role", role],
        }
        for role in guarded_roles(profiles)
    }
    return {"mcpServers": servers}


def write_mcp(root: Path, profiles: dict[str, Any]) -> Path:
    """Write the generated file under root and return its path."""
    path = root / MCP_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mcp_config(profiles), indent=2) + "\n", encoding="utf-8")
    return path


def check_mcp(root: Path, profiles: dict[str, Any]) -> list[str]:
    """One line per way capabilities/mcp.json differs from the generator output."""
    path = root / MCP_PATH
    try:
        found = cast("object", json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return [f"mcp: {MCP_PATH} missing or unreadable (run capability_profiles_validate.py --write-mcp)"]
    want: dict[str, Any] = mcp_config(profiles)["mcpServers"]
    top = cast("dict[str, Any]", found) if isinstance(found, dict) else {}
    servers = top.get("mcpServers")
    if not isinstance(servers, dict):
        return [f"mcp: {MCP_PATH} has no mcpServers object"]
    declared = cast("dict[str, Any]", servers)
    errors = [f"mcp: server {name} is not a guarded role in the profile" for name in sorted(set(declared) - set(want))]
    errors += [f"mcp: server {name} missing from {MCP_PATH}" for name in sorted(set(want) - set(declared))]
    errors += [
        f"mcp: server {name} differs from the generated entry"
        for name in sorted(want)
        if name in declared and declared[name] != want[name]
    ]
    if set(top) != {"mcpServers"}:
        errors.append(f"mcp: {MCP_PATH} has keys other than mcpServers")
    return errors


def claude_errors(name: str, caps: list[str], tools: list[str]) -> list[str]:
    """Errors for a guarded Claude agent's frontmatter tools: exact derived set, no forbidden tool, names within 64."""
    errors: list[str] = []
    want = expected_tools(name, caps)
    bad = sorted(set(tools) & FORBIDDEN_TOOLS)
    if bad:
        errors.append(f"claude: {name} guarded agent lists forbidden tools {bad}")
    extra, missing = sorted(set(tools) - set(want) - set(bad)), sorted(set(want) - set(tools))
    if extra or missing or len(tools) != len(set(tools)):
        errors.append(f"claude: {name} tools differ from the derived MCP names: extra {extra} missing {missing}")
    return errors


def length_errors(name: str, caps: list[str]) -> list[str]:
    """A guarded role whose full MCP tool name exceeds the API limit would be rejected at runtime."""
    return [
        f"claude: {name} tool name {t} is {len(t)} characters, over the {MAX_TOOL_NAME} limit"
        for t in expected_tools(name, caps)
        if guarded(caps) and len(t) > MAX_TOOL_NAME
    ]


def codex_errors(name: str, text: str) -> list[str]:
    """A guarded Codex agent must switch the shell tool off; sandbox_mode alone does not bind a child.

    Multi-line strings are blanked first so a forged `[features]` / `sandbox_mode` line inside developer_instructions
    cannot satisfy the line checks (tomllib is not available on every supported Python).
    """
    text = re.sub(r'(?s)""".*?"""|\'\'\'.*?\'\'\'', '""', text)
    on = re.search(r"(?ms)^\[features\]\s*\n(.*?)(?=^\[|\Z)", text)
    if not on or not re.search(r"(?m)^shell_tool\s*=\s*false\s*$", on.group(1)):
        return [f"codex: {name} guarded agent needs [features] shell_tool = false"]
    key = re.search(r"(?m)^developer_instructions\s*=", text)
    if key and key.start() > on.start():
        return [f"codex: {name} [features] must come after developer_instructions (a table before it swallows the key)"]
    if not re.search(r'(?m)^sandbox_mode\s*=\s*"read-only"', text):
        return [f'codex: {name} guarded agent must keep sandbox_mode = "read-only"']
    return []
