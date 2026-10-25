#!/usr/bin/env python3
"""Preview or activate the GitHub Actions integrity ruleset with the owner's gh login."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

from integrity_http import IntegrityError
from integrity_setup import configure_ruleset


def repository() -> str:
    """Resolve only the authenticated repository named by gh."""
    result = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        capture_output=True,
        text=True,
        check=False,
    )
    slug = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", slug):
        raise ValueError("could not resolve the authenticated GitHub repository")
    return slug


def main(argv: list[str] | None = None) -> int:
    """Refuse activation until a real Actions result exists on a candidate PR."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-pr", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="create the verified server rule")
    arguments = parser.parse_args(argv)
    if arguments.candidate_pr < 1:
        parser.error("--candidate-pr must be positive")
    try:
        slug = repository()
        result = configure_ruleset(slug, arguments.candidate_pr, apply=arguments.apply)
    except (OSError, ValueError, IntegrityError) as error:
        print(f"integrity setup refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    print("Ruleset active and checked." if arguments.apply else "Preview only. Add --apply after review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
