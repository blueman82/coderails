#!/usr/bin/env python3
"""Print the memory directory for a working directory: `memory_dir.py [--cwd DIR] [--provider claude|codex]`.

The folder is `~/.<provider>/projects/<slug>/memory` where `<slug>` is the realpath of the directory with every
character outside [A-Za-z0-9] replaced by `-` (so `/Users/x/Github/proj` is `-Users-x-Github-proj`, and `.`/`_`
become `-` exactly as the existing project folders show). The path is printed whether or not it exists.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


def memory_dir(cwd: str, provider: str = "claude") -> Path:
    """The provider's memory directory for cwd."""
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd))
    return Path.home() / f".{provider}" / "projects" / slug / "memory"


def main(argv: list[str] | None = None) -> int:
    """CLI entry."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--provider", choices=("claude", "codex"), default="claude")
    args = parser.parse_args(argv)
    print(memory_dir(args.cwd, args.provider))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
