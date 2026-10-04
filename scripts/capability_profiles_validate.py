#!/usr/bin/env python3
"""Check capabilities/profiles.json against Claude agent frontmatter and Codex agent sandbox modes."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hooks.scripts.lib.capability_profiles import TOOLS, load_profiles

NEEDS_INSTRUCTION = ("tests.run", "pr.comment")


def frontmatter(text: str) -> dict[str, list[str]]:
    """Parse `key: a, b` lines between the leading --- fences into lists."""
    match = re.match(r"---\n(.*?)\n---", text, re.S)
    rows = (line.split(":", 1) for line in (match.group(1).splitlines() if match else []) if ":" in line)
    return {k.strip(): [v.strip() for v in rest.split(",") if v.strip()] for k, rest in rows}


def validate(root: Path, profiles: dict[str, Any]) -> list[str]:
    """Return one line per disagreement; an empty list means the three sources agree."""
    errors: list[str] = []
    known = set(profiles.get("capabilities", []))
    agents: dict[str, list[str]] = profiles["agents"]
    if not set(TOOLS) <= known:
        errors.append("profiles: capabilities must include every capability tool")
    for name, caps in agents.items():
        errors += [f"{name}: unknown capability {cap}" for cap in caps if cap not in known]
    for name, argv in profiles.get("tests", {}).items():
        if not argv or not all(isinstance(a, str) for a in argv):
            errors.append(f"tests.{name}: must be a non-empty argv list of strings")
    claude = {p.stem: p for p in (root / "agents").glob("*.md")}
    codex = {p.stem: p for p in (root / "packages/codex/agents").glob("*.toml")}
    for name in sorted(set(agents) | set(claude) | set(codex)):
        for harness, files in (("claude", claude), ("codex", codex)):
            if name in files and name not in agents:
                errors.append(f"{harness}: {name} has no profile")
            if name in agents and name not in files:
                errors.append(f"{harness}: profile {name} has no agent file")
    for name, caps in agents.items():
        write = "worktree.write" in caps
        tool_caps = any(cap in TOOLS for cap in caps)
        needs = [cap for cap in caps if cap in NEEDS_INSTRUCTION]
        if name in claude:
            text = claude[name].read_text(encoding="utf-8")
            meta = frontmatter(text)
            tools = set(meta.get("tools", [])) - set(meta.get("disallowedTools", []))
            if write != bool({"Write", "Edit"} & tools):
                errors.append(f"claude: {name} worktree.write={write} disagrees with frontmatter tools")
            if ("Bash" in tools) != (tool_caps or "shell.raw" in caps):
                errors.append(f"claude: {name} Bash tool disagrees with shell.raw/capability tools in profile")
            if needs and "capability.py" not in text:
                errors.append(f"claude: {name} profile grants {needs} but agent text never names capability.py")
        if name in codex:
            text = codex[name].read_text(encoding="utf-8")
            sandbox = re.search(r'^sandbox_mode\s*=\s*"([^"]+)"', text, re.M)
            if write != (sandbox is None or sandbox.group(1) != "read-only"):
                errors.append(f"codex: {name} worktree.write={write} disagrees with sandbox_mode")
            if needs and "capability.py" not in text:
                errors.append(f"codex: {name} profile grants {needs} but agent text never names capability.py")
    return errors


def main() -> int:
    """Print every disagreement and exit 1, or exit 0 when the profiles agree."""
    root = Path(__file__).resolve().parents[1]
    errors = validate(root, load_profiles(root))
    print("\n".join(errors) if errors else "capability profiles OK")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
