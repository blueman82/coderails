#!/usr/bin/env python3
"""Wiki staleness check: `wiki_lint.py stale --repo R --vault V` prints JSON {stale_days, candidates, stale, data_gaps}.

A page is a candidate when `last_updated` is more than `wiki_stale_days` (typed config, default 30) old. A candidate
is stale when a resolvable source's last commit date is more than GRACE_DAYS after `last_updated`; a candidate with no
repo-resolvable source at all is stale on date alone (`basis: date-only`). Sources resolve as the wiki-lint skill says:
`$repo/<entry>`, then `$repo/<entry minus .md>/SKILL.md`, then a vault page (skipped), else unresolvable (a data gap).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.lib.config import config_path, load_config

GRACE_DAYS = 7
POINT_IN_TIME = {".git", ".obsidian", "assets", "dashboard-runs", "inbox", "investigations", "sources", "templates"}
SKIP_FILES = {"index.md", "log.md", "AGENTS.md"}
FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[str, list[str]]:
    """(last_updated text, sources list) from a page's frontmatter; missing parts come back empty."""
    match = FRONT.match(text)
    updated, sources, in_sources = "", [], False
    for line in (match.group(1) if match else "").splitlines():
        if line.startswith("last_updated:"):
            updated = line.split(":", 1)[1].split("#", 1)[0].strip().strip("\"'")
        elif line.startswith("sources:"):
            rest = line.split(":", 1)[1].split("#", 1)[0].strip()
            in_sources = not rest
            if rest.startswith("["):
                sources = [item.strip().strip("\"'") for item in rest.strip("[]").split(",") if item.strip()]
        elif in_sources and line.lstrip().startswith("- "):
            sources.append(line.lstrip()[2:].split("#", 1)[0].strip().strip("\"'"))
        elif line and not line[0].isspace():
            in_sources = False
    return updated, sources


def resolve(entry: str, repo: Path, vault: Path) -> tuple[str, str]:
    """(kind, repo-relative path): kind is repo, vault or none. Repo forms are tried before the vault."""
    for candidate in (entry, entry[:-3] + "/SKILL.md" if entry.endswith(".md") else ""):
        if candidate and (repo / candidate).is_file():
            return "repo", candidate
    return ("vault", entry) if (vault / entry).exists() else ("none", entry)


def commit_date(repo: Path, relative: str) -> date | None:
    """Last commit date of a path on the current branch; empty output is not a date."""
    result = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%cs", "--", relative],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return date.fromisoformat(result.stdout.strip())
    except ValueError:
        return None


def pages(vault: Path) -> list[Path]:
    """Every checkable page in the vault, excluding point-in-time and structural directories."""
    return sorted(
        path
        for path in vault.rglob("*.md")
        if not POINT_IN_TIME.intersection(path.relative_to(vault).parts[:-1]) and path.name not in SKIP_FILES
    )


def stale_report(repo: Path, vault: Path, today: date) -> dict[str, object]:
    """Apply the staleness rule to every page."""
    values, _ = load_config(config_path(repo))
    days = int(values.get("wiki_stale_days") or 30)
    candidates: list[str] = []
    stale: list[dict[str, object]] = []
    gaps: list[dict[str, str]] = []
    for path in pages(vault):
        name = str(path.relative_to(vault))
        updated_text, sources = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        try:
            updated = date.fromisoformat(updated_text[:10])
        except ValueError:
            gaps.append({"page": name, "source": "", "reason": "last_updated_missing"})
            continue
        if today - updated <= timedelta(days=days):
            continue
        candidates.append(name)
        moved: list[dict[str, str]] = []
        comparable = 0
        for entry in sources:
            kind, relative = resolve(entry, repo, vault)
            if kind == "none":
                gaps.append({"page": name, "source": entry, "reason": "unresolvable"})
            elif kind == "repo":
                found = commit_date(repo, relative)
                if found is None:
                    gaps.append({"page": name, "source": entry, "reason": "no_commit_date"})
                    continue
                comparable += 1
                if found > updated + timedelta(days=GRACE_DAYS):
                    moved.append({"source": relative, "commit_date": found.isoformat()})
        if moved or not comparable:
            basis = "sources" if moved else "date-only"
            stale.append({"page": name, "last_updated": updated.isoformat(), "basis": basis, "moved": moved})
    return {"stale_days": days, "candidates": candidates, "stale": stale, "data_gaps": gaps}


def main(argv: list[str] | None = None) -> int:
    """CLI entry: the only subcommand is `stale`."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    stale = sub.add_parser("stale", help="print the staleness report as JSON")
    stale.add_argument("--repo", type=Path, required=True)
    stale.add_argument("--vault", type=Path, required=True)
    stale.add_argument("--today", default="", help="YYYY-MM-DD override (tests)")
    args = parser.parse_args(argv)
    today = date.fromisoformat(args.today) if args.today else date.today()
    print(json.dumps(stale_report(args.repo.resolve(), args.vault.resolve(), today), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
