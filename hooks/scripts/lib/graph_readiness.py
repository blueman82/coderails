#!/usr/bin/env python3
"""Print ready or blocked using the installed current graph semantics."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.graph_executor import ready_nodes


def main(arguments: list[str] | None = None) -> int:
    """Fail closed on missing arguments, unreadable state or blocked dependencies."""
    arguments = sys.argv[1:] if arguments is None else arguments
    try:
        allowed = len(arguments) == 2 and arguments[1] in ready_nodes(Path(arguments[0]))
    except ValueError:
        allowed = False
    print("ready" if allowed else "blocked")
    return 0 if allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
