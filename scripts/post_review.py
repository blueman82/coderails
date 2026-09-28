#!/usr/bin/env python3
"""Validate review summaries and cache posted review identity atomically."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hooks.scripts.lib.loop_state_common import atomic_progress_update
from scripts.lib.artifact_io import JsonObject


def validate_summary(path: str | Path) -> None:
    """Require no-findings or all populated severity sections without ambiguity."""
    if not Path(path).is_file():
        raise ValueError(f"file not found: {path}")
    lines = Path(path).read_text().splitlines()
    headings = ("## Critical", "## Important", "## Suggestions")
    if "## No findings" in lines:
        if any(heading in lines for heading in headings):
            raise ValueError('ambiguous — "## No findings" present alongside structured headings')
        return
    missing = [heading for heading in headings if heading not in lines]
    if missing:
        raise ValueError(f"missing required headings: {' '.join(missing)}")
    for heading in headings:
        populated = False
        for line in lines[lines.index(heading) + 1 :]:
            if line.startswith("## "):
                break
            if line.startswith("- ") or line == "None":
                populated = True
                break
        if not populated:
            raise ValueError(f'section "{heading}" has no bullet or None')


def write_cache(path: str | Path, pr: str, head_sha: str, url: str, author: str, posted_at: str) -> int:
    """Write review metadata under the provider-local progress lock, if present."""
    destination = Path(path)
    if not destination.is_file():
        print(f"write_cache: progress.json not found at {path} — skipping cache write", file=sys.stderr)
        return 0

    def update(data: JsonObject) -> JsonObject:
        """Replace the cache in the locked current document."""
        data["review"] = {
            "ran": True,
            "pr": int(pr),
            "head_sha": head_sha,
            "summary_posted": True,
            "summary_url": url,
            "summary_author": author,
            "posted_at": posted_at,
        }
        return data

    if not atomic_progress_update(destination, update):
        print("write_cache: update failed — progress.json left unchanged", file=sys.stderr)
        return 1
    return 0


def main(arguments: list[str] | None = None) -> int:
    """Dispatch summary validation and best-effort cache writes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("validate", "write-cache"))
    parser.add_argument("path")
    parser.add_argument("arguments", nargs="*")
    try:
        args = parser.parse_args(arguments)
    except SystemExit as error:
        return int(bool(error.code))
    try:
        if args.operation == "validate":
            validate_summary(args.path)
            return 0
        if len(args.arguments) != 5:
            raise ValueError("write-cache requires <path> <pr> <sha> <url> <author> <iso8601>")
        return write_cache(args.path, *args.arguments)
    except (OSError, ValueError) as error:
        print(f"{args.operation}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
