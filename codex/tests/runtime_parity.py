#!/usr/bin/env python3
"""Keep the standalone package graph runtime generated from the source runtime."""

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[2]
CHECK = ROOT / "codex/scripts/sync_package_runtime.py"


def main() -> int:
    result = subprocess.run([sys.executable, str(CHECK), "--check"], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr or result.stdout
    assert (ROOT / "packages/codex/runtime/graph.py").read_bytes() == (ROOT / "codex/runtime/graph.py").read_bytes()
    assert (ROOT / "packages/codex/runtime/contract.py").read_bytes() == (ROOT / "codex/runtime/contract.py").read_bytes()
    assert (ROOT / "packages/codex/runtime/codex_exec.py").read_bytes() == (ROOT / "codex/runtime/codex_exec.py").read_bytes()
    print("PASS: standalone package graph runtime has no hand-maintained drift")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
