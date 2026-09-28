#!/usr/bin/env python3
"""Validate native Codex review summaries before posting authoritative PR evidence."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def validate_summary(path: str | Path) -> None:
    """Require no-findings or all populated severity sections without ambiguity."""
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


def main() -> int:
    """Validate the summary without creating provider-local review caches."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("validate",))
    parser.add_argument("path", type=Path)
    try:
        args = parser.parse_args()
    except SystemExit as error:
        return int(bool(error.code))
    try:
        validate_summary(args.path)
    except (OSError, ValueError) as error:
        print(f"validate_summary: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
