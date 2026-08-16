#!/usr/bin/env python3
"""Sync the standalone package's generated graph runtime from the source."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).parents[2]
SOURCE = ROOT / "codex/runtime/graph.py"
TARGET = ROOT / "packages/codex/runtime/graph.py"
ADAPTER_SOURCE = ROOT / "codex/runtime/codex_exec.py"
ADAPTER_TARGET = ROOT / "packages/codex/runtime/codex_exec.py"
PRODUCER_SOURCE = ROOT / "codex/runtime/gate_producer.py"
PRODUCER_TARGET = ROOT / "packages/codex/runtime/gate_producer.py"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the generated package copy differs from the source",
    )
    args = parser.parse_args()

    source = SOURCE.read_bytes()
    if args.check:
        if (not TARGET.is_file() or TARGET.read_bytes() != source or
                not ADAPTER_TARGET.is_file() or ADAPTER_TARGET.read_bytes() != ADAPTER_SOURCE.read_bytes() or
                not PRODUCER_TARGET.is_file() or PRODUCER_TARGET.read_bytes() != PRODUCER_SOURCE.read_bytes()):
            print(f"generated runtime is stale: {TARGET.relative_to(ROOT)}", file=sys.stderr)
            return 1
        print("PASS: package graph runtime matches codex/runtime/graph.py")
        return 0

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, TARGET)
    shutil.copy2(ADAPTER_SOURCE, ADAPTER_TARGET)
    shutil.copy2(PRODUCER_SOURCE, PRODUCER_TARGET)
    print(f"synced {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
