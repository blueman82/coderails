#!/usr/bin/env python3
"""Seed due provider-local routines, then sweep even when seeding fails."""

import os
import subprocess
import sys
from pathlib import Path

NODE = "/opt/homebrew/bin/node"
RUNNER = Path(__file__).resolve().parent.parent
SEED = RUNNER / "src/seedMain.ts"
TARGET = RUNNER / "src/main.ts"


def main() -> None:
    """Preserve the seed failure diagnostic and foreground sweep process ownership."""
    try:
        status = subprocess.run([NODE, str(SEED)], check=False).returncode
        if status < 0:
            status = 128 - status
    except OSError as error:
        print(error, file=sys.stderr)
        status = 127
    if status:
        print(f"seed step failed (exit {status}), continuing to sweep", file=sys.stderr)
    os.execv(NODE, [NODE, str(TARGET)])


if __name__ == "__main__":
    main()
