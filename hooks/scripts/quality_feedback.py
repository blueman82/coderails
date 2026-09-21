#!/usr/bin/env python3
"""Warn-only quality feedback for an edited supported file."""

from __future__ import annotations

import subprocess
from pathlib import Path

from hook_common import read_payload

SUFFIXES = {".bash", ".cfg", ".js", ".json", ".jsx", ".md", ".py", ".sh", ".toml", ".ts", ".tsx", ".yaml", ".yml"}


def main() -> int:
    """Run warn-only source-quality feedback for a supported changed file."""
    payload = read_payload()
    data = payload.get("tool_input")
    response = payload.get("tool_response")
    if not isinstance(data, dict):
        data = {}
    if not isinstance(response, dict):
        response = {}
    file = data.get("file_path") or response.get("filePath")
    if not isinstance(file, str) or not Path(file).is_file() or Path(file).suffix not in SUFFIXES:
        return 0
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["python3", str(root / "scripts/quality/check.py"), "--root", str(root), "--paths", file],
        capture_output=True,
        text=True,
        check=False,
    )
    text = result.stdout + result.stderr
    if "0 finding(s)" not in text:
        print(f"coderails quality feedback (warn-only): {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
