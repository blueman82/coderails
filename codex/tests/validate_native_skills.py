#!/usr/bin/env python3
"""Validate the provider-native Codex skill tree."""

from pathlib import Path
import re
import sys
from urllib.parse import unquote

ROOT = Path(__file__).parents[2]
SKILLS = ROOT / ".codex" / "skills"
ACTIVE = re.compile(r"^  ([a-z0-9][a-z0-9-]*):$", re.M)
LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")
FORBIDDEN = ("CLAUDE_PLUGIN_ROOT", "CLAUDE_CODE_SESSION_ID", "~/.claude/", "hooks/hooks.json")


def main() -> int:
    index = (ROOT / "skills" / "index.yaml").read_text(encoding="utf-8")
    names: list[str] = []
    current: str | None = None
    for line in index.splitlines():
        if match := ACTIVE.match(line):
            current = match.group(1)
        elif line.startswith("  ") and not line.startswith("    "):
            current = None
        elif current and line.strip() == "source_kind: skill":
            names.append(current)
    errors: list[str] = []
    for name in names:
        path = SKILLS / name / "SKILL.md"
        if not path.is_file():
            errors.append(f"missing native skill: {path.relative_to(ROOT)}")
    for path in SKILLS.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN:
            if token in text:
                errors.append(f"provider dependency {token!r}: {path.relative_to(ROOT)}")
        for target in LINK.findall(text):
            target = unquote(target.split("#", 1)[0])
            if not target or "://" in target:
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.is_file() or SKILLS not in resolved.parents:
                errors.append(f"unresolved/out-of-tree link {target!r}: {path.relative_to(ROOT)}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"PASS: {len(names)} native Codex skills; markdown links and provider boundaries valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
