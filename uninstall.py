#!/usr/bin/env python3
"""Reverse the Claude dotfile changes while preserving user memories and logs."""

import sys
from pathlib import Path

from scripts.installer.claude import uninstall


def main() -> int:
    """Remove managed local settings, leaving plugin deregistration to Claude."""
    try:
        uninstall(Path.home())
        return 0
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
