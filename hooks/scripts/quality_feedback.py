#!/usr/bin/env python3
"""Warn-only quality feedback for an edited supported file."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import read_payload

SUFFIXES = {".bash", ".cfg", ".js", ".json", ".jsx", ".md", ".py", ".sh", ".toml", ".ts", ".tsx", ".yaml", ".yml"}


def finding_lines(result: subprocess.CompletedProcess[str]) -> list[str]:
    """Validate structured findings and disclose external or checker failures."""
    try:
        raw: object = json.loads(result.stdout)
        if not isinstance(raw, dict):
            raise ValueError("invalid quality result")
        data = cast("dict[str, Any]", raw)
        if (
            type(data.get("scanned")) is not int
            or data["scanned"] < 0
            or not isinstance(data.get("findings"), list)
            or type(data.get("external_ok")) is not bool
        ):
            raise ValueError("invalid quality result")
        lines: list[str] = []
        for raw_issue in cast("list[object]", data["findings"]):
            if not isinstance(raw_issue, dict):
                raise ValueError("invalid finding")
            issue = cast("dict[str, Any]", raw_issue)
            if (
                not isinstance(issue.get("path"), str)
                or not isinstance(issue.get("message"), str)
                or not (issue.get("line") is None or type(issue["line"]) is int and issue["line"] > 0)
            ):
                raise ValueError("invalid finding")
            lines.append(f"{issue['path']}:{issue['line'] or ''}: {issue['message']}")
        if not data["external_ok"]:
            lines.append(f"external quality checks failed: {result.stderr.strip()[:500]}")
        elif result.returncode:
            lines.append(f"quality checker failed (exit {result.returncode}): {result.stderr.strip()[:500]}")
        return lines
    except (ValueError, KeyError, TypeError):
        return [f"quality check produced unusable JSON: {result.stderr.strip()[:500]}"]


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
    lines = finding_lines(result)
    if lines:
        print("coderails quality feedback (warn-only): " + "\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
