"""Read capabilities/profiles.json, the single source for which agent may reach which capability."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Capabilities reached through scripts/capability.py <tool>; the others are harness-level (Write/Edit, raw Bash).
TOOLS = ("repo.inspect", "diff.read", "tests.run", "pr.comment")


def load_profiles(root: Path) -> dict[str, Any]:
    """Return the parsed profiles under root; raises on a missing or malformed file."""
    data: dict[str, Any] = json.loads((root / "capabilities" / "profiles.json").read_text(encoding="utf-8"))
    if not isinstance(data["agents"], dict):
        raise ValueError("capabilities/profiles.json: 'agents' object required")
    return data


def guarded_agents(profiles: dict[str, Any]) -> frozenset[str]:
    """Agents whose Bash is capability-only (a capability tool, no shell.raw): held to the Bash allowlist."""
    return frozenset(
        name
        for name, caps in profiles["agents"].items()
        if "shell.raw" not in caps and any(cap in TOOLS for cap in caps)
    )


def may_use(profiles: dict[str, Any], agent: str, tool: str) -> bool:
    """True when the agent's profile grants the tool (shell.raw already reaches everything a tool does)."""
    caps = profiles["agents"].get(agent, [])
    return tool in caps or "shell.raw" in caps
