#!/usr/bin/env python3
"""Warn-only quality feedback for an edited supported file."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import read_payload

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
        ["python3", str(root / "scripts/quality/check.py"), "--json", "--root", str(root), "--paths", file],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        lines = [f"{i['path']}:{i['line'] or ''}: {i['message']}" for i in json.loads(result.stdout)["findings"]]
    except (ValueError, KeyError, TypeError):
        # the checker itself broke: say so rather than reading silence as "clean"
        lines = [f"quality check produced no JSON: {result.stderr.strip()[:500]}"]
    if lines:
        print("coderails quality feedback (warn-only): " + "\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
