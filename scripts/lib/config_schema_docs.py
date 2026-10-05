"""Render the workflow-config key table from config.schema.json into docs/REFERENCE.md."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
START = "<!-- config-schema:start -->"
END = "<!-- config-schema:end -->"


def rows(properties: dict[str, Any], prefix: str = "") -> list[str]:
    """One markdown row per key, nested keys dotted."""
    lines: list[str] = []
    for key, spec in properties.items():
        kind = "/".join(spec["type"])
        default = json.dumps(spec["default"])
        text = spec["description"].replace("|", "\\|")
        lines.append(f"| `{prefix}{key}` | {kind} | `{default}` | {spec['status']} | {text} |")
        lines += rows(spec.get("properties", {}), prefix + key + ".")
    return lines


def table(schema_path: Path = ROOT / "config.schema.json") -> str:
    """The full generated block, markers included."""
    schema = cast("dict[str, Any]", json.loads(schema_path.read_text(encoding="utf-8")))
    head = ["| Key | Type | Default | Status | Description |", "|---|---|---|---|---|"]
    return "\n".join([START, *head, *rows(schema["properties"]), END])


def splice(document: str, block: str) -> str:
    """Replace the marked block in document; raises ValueError when the markers are absent."""
    start, end = document.index(START), document.index(END) + len(END)
    return document[:start] + block + document[end:]


def main() -> int:
    """--write regenerates the block in docs/REFERENCE.md in place."""
    path = ROOT / "docs/REFERENCE.md"
    document = path.read_text(encoding="utf-8")
    updated = splice(document, table())
    if "--write" in sys.argv[1:]:
        path.write_text(updated, encoding="utf-8")
    return 0 if updated == document else 1


if __name__ == "__main__":
    raise SystemExit(main())
