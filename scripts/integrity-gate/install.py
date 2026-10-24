#!/usr/bin/env python3
"""Retired root-owned daemon installer."""

import sys


def main() -> int:
    """Direct owners to the GitHub Actions integrity gate setup."""
    print(
        "INTEGRITY INSTALL RETIRED — use GitHub Actions setup: "
        "python3 scripts/integrity-gate/setup.py --candidate-pr <PR number>",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
