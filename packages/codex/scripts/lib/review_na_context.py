"""Complete N/A context rows, compact display and one immutable batch blob read."""

from __future__ import annotations

import json
import subprocess
from typing import Any


def inventory(trees: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """All tracked non-tree paths outside the authored page endpoints, without suffix assumptions."""
    pages = {entry["path"] for row in rows for entry in (row["old"], row["new"]) if entry}
    paths = {path for tree in trees.values() for path, entry in tree.items() if entry["type"] != "tree"} - pages
    result: list[dict[str, Any]] = []
    for path in sorted(paths):
        row: dict[str, Any] = {"path": path}
        for name, tree in trees.items():
            entry = tree.get(path)
            if entry and (entry["type"] != "blob" or entry["mode"] not in ("100644", "100755")):
                raise ValueError("N/A consumer type or mode invalid")
            row[name] = entry
        result.append(row)
    return result


def check_blobs(objects: set[str]) -> None:
    """Check all needed immutable blobs with one process and no path interpretation or object filters."""
    if not objects:
        return
    ordered = sorted(objects)
    reply = subprocess.run(
        ["git", "--no-replace-objects", "cat-file", "--batch-check"],
        input="\n".join(ordered) + "\n",
        text=True,
        capture_output=True,
        check=False,
    )
    lines = reply.stdout.splitlines()
    if reply.returncode or len(lines) != len(ordered):
        raise ValueError("N/A blob batch unavailable")
    for oid, line in zip(ordered, lines):
        fields = line.split()
        if len(fields) != 3 or fields[:2] != [oid, "blob"] or not fields[2].isdigit():
            raise ValueError("N/A blob missing or wrong type")


def compact(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate identical path/entry facts without dropping their exact tree membership."""
    compact: list[dict[str, Any]] = []
    for row in rows:
        groups: dict[str, dict[str, Any]] = {}
        for name in ("merge_base", "base", "head"):
            entry = row[name]
            if entry:
                key = json.dumps(entry, sort_keys=True)
                if key not in groups:
                    groups[key] = {"path": row["path"], **entry, "at": []}
                groups[key]["at"].append(name)
        compact.extend(groups.values())
    return compact
