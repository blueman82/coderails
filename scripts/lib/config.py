"""Resolve the nearest workflow configuration within the containing repository."""

from __future__ import annotations

import argparse
import contextlib
import copy
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast


def config_path(start_dir: str | Path | None = None) -> str:
    """Return the nearest config path, or empty text outside configured repositories."""
    start = Path(start_dir or Path.cwd()).resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
        )
        if result.returncode or not result.stdout.strip():
            return ""
        root = Path(result.stdout.strip()).resolve()
        current = start
        while True:
            candidate = current / ".coderails/workflow.config.yaml"
            if candidate.is_file():
                return str(candidate)
            if current == root or current == current.parent:
                return ""
            current = current.parent
    except OSError:
        return ""


def resolve_config(start_dir: str | Path | None = None) -> str:
    """Read the discovered file or return the NO_CONFIG sentinel."""
    path = config_path(start_dir)
    return Path(path).read_text() if path else "NO_CONFIG\n"


def config_value(path: str | Path, key: str, section: str = "") -> str:
    """Read a workflow scalar using the existing single-level configuration grammar."""
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return ""
    active = not section
    for line in lines:
        if section and re.fullmatch(re.escape(section) + r":\s*", line):
            active = True
            continue
        if section and line and not line[0].isspace():
            active = False
        prefix = r"\s+" if section else ""
        match = re.match(prefix + re.escape(key) + r":\s*(.*)$", line)
        if active and match:
            return match[1].split("#", 1)[0].strip().strip("\"'")
    return ""


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config.schema.json"
KEY_LINE = re.compile(r"(\s*)([A-Za-z_][\w-]*):[ \t]*(.*)")
NULLS = frozenset({"null", "~"})


def _schema() -> dict[str, Any]:
    """Return the schema; on any failure an empty one, so every key stays a raw (still readable) unknown."""
    try:
        data = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        return cast("dict[str, Any]", data) if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _entries(text: str) -> dict[str, dict[str, Any]]:
    """Parse the single-level grammar plus one nested level: {key: {raw, items, children}}."""
    top: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    indent = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line[0].isspace():
            match = KEY_LINE.fullmatch(line)
            current = {"raw": "", "items": [], "children": {}} if match else None
            indent = None
            if match and current is not None:
                current["raw"] = match[3].split("#", 1)[0].strip().strip("\"'")
                top[match[2]] = current
        elif current is not None and stripped.startswith("- "):
            current["items"].append(stripped[2:].split("#", 1)[0].strip().strip("\"'"))
        elif current is not None and (match := KEY_LINE.fullmatch(line)):
            indent = len(match[1]) if indent is None else indent
            if len(match[1]) == indent:
                current["children"][match[2]] = {"raw": match[3].split("#", 1)[0].strip().strip("\"'")}
    return top


def _coerce(entry: dict[str, Any], spec: dict[str, Any]) -> tuple[Any, bool]:
    """Return (value, ok); a value that fits no allowed type is returned raw with ok False."""
    types = spec.get("type", [])
    raw = entry["raw"]
    if entry.get("children") and "object" in types:
        return {key: child["raw"] for key, child in entry["children"].items()}, True
    if entry.get("items") and "array" in types:
        return list(entry["items"]), True
    if raw == "":
        return None, not (entry.get("items") or entry.get("children"))
    if raw in NULLS:
        return (None, True) if "null" in types else (raw, False)
    if "boolean" in types and raw.lower() in ("true", "false"):
        return raw.lower() == "true", True
    if "integer" in types and re.fullmatch(r"[0-9]+", raw):
        return int(raw), True
    if "array" in types and raw.startswith("[") and raw.endswith("]"):
        return [item.strip().strip("\"'") for item in raw[1:-1].split(",") if item.strip()], True
    return raw, "string" in types


def _hint(key: str, known: dict[str, Any]) -> str:
    """Closest known key, or empty text."""
    close = difflib.get_close_matches(key, list(known), n=1, cutoff=0.6)
    return close[0] if close else ""


def _typed(
    entries: dict[str, dict[str, Any]], properties: dict[str, Any], prefix: str, findings: list[dict[str, str]]
) -> dict[str, Any]:
    """Coerce one level against its properties; unknown keys stay raw and are reported."""
    values: dict[str, Any] = {}
    for key, entry in entries.items():
        spec = properties.get(key)
        if spec is None:
            hint = _hint(key, properties)
            findings.append({"code": "config_unknown_key", "key": prefix + key, "hint": prefix + hint if hint else ""})
            values[key] = entry["raw"]
            continue
        value, ok = _coerce(entry, spec)
        if not ok:
            findings.append({"code": "config_bad_type", "key": prefix + key, "hint": "/".join(spec["type"])})
        elif isinstance(value, dict) and spec.get("properties"):
            nested = cast("dict[str, Any]", value)
            value = _typed({k: {"raw": v} for k, v in nested.items()}, spec["properties"], prefix + key + ".", findings)
        values[key] = value
    for key, spec in properties.items():
        if key not in values:
            values[key] = copy.deepcopy(spec.get("default"))
    return values


def load_config(path: str | Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Parse path against config.schema.json: (typed values with defaults, reason-coded findings). Never raises."""
    properties: dict[str, Any] = _schema().get("properties", {})
    findings: list[dict[str, str]] = []
    text = ""
    if path:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, ValueError):
            findings.append({"code": "config_unreadable", "key": "", "hint": ""})
    return _typed(_entries(text), properties, "", findings), findings


def _append_row(code: str, key: str, session: str) -> None:
    """One fail-open trace row (same shape as hooks/scripts/lib/trace_row.py; shipped in both packages)."""
    if not session or session in {"?", "."} or "/" in session or ".." in session or "\0" in session:
        return
    root = Path(os.environ.get("CLAUDE_AGENTIC_LOOP_DIR") or os.environ.get("CODERAILS_AGENTIC_LOOP_DIR") or "")
    root = root if str(root) not in ("", ".") else Path.home() / ".coderails/agentic-loop"
    row = {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "session_id": session,
        "loop_id": None,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": "config",
        "outcome": "warned",
        "reason_code": code,
        "inputs": {"key": hashlib.sha256(key.encode("utf-8")).hexdigest()},
    }
    try:
        path = root / session / "trace.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(descriptor, (json.dumps(row, sort_keys=True) + "\n").encode("utf-8"))
        finally:
            os.close(descriptor)
    except OSError:
        return


def report_findings(findings: list[dict[str, str]], session: str = "") -> None:
    """Non-authoritative visibility: one stderr line plus fail-open trace rows. Never changes a decision."""
    if not findings:
        return
    print("coderails config: " + ", ".join(f"{f['code']}:{f['key']}" for f in findings), file=sys.stderr)
    who = session or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    for finding in findings:
        _append_row(finding["code"], finding["key"], who)


def settings(path: str | Path, session: str = "") -> dict[str, Any]:
    """Typed values for a gate reader, with findings reported (session: hook payload id when env has none)."""
    values, findings = load_config(path)
    report_findings(findings, session)
    return values


def wiki_page_types(path: str | Path) -> tuple[list[str], str]:
    """Allowed wiki top-level dirs (page_types + structural_dirs) from wiki.schema.json.

    Returns (names, "") or ([], wiki_schema_missing|wiki_schema_invalid).
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return [], "wiki_schema_missing"
    except ValueError:
        return [], "wiki_schema_invalid"
    fields = cast("dict[str, Any]", data) if isinstance(data, dict) else {}
    types = fields.get("page_types")
    extra = fields.get("structural_dirs", [])
    if not isinstance(types, list) or not types or not isinstance(extra, list):
        return [], "wiki_schema_invalid"
    names = cast("list[object]", types) + cast("list[object]", extra)
    if not all(isinstance(n, str) and re.fullmatch(r"[A-Za-z0-9_-]+", n) for n in names):
        return [], "wiki_schema_invalid"
    return [str(n) for n in names], ""


def legacy_page_types(path: str | Path) -> list[str]:
    """Top-level dirs from the '## Page types' section of a pre-wiki.schema.json AGENTS-wiki-schema.md, else []."""
    try:
        sections = re.split(r"(?m)^## ", Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    section = next((part for part in sections if part.startswith("Page types\n")), "")
    return [name[:-1] for name in re.findall(r"`([A-Za-z0-9_-]+/)`", section)]


def _section(path: str | Path, key: str) -> dict[str, Any]:
    """One typed nested section of the config at path, or {}."""
    value = settings(path).get(key)
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def integrity_machine_user(path: str | Path) -> str:
    """Read the configured root-owned attestor login; null or absent means inactive."""
    return str(_section(path, "integrity_review").get("machine_user") or "")


def require_signatures(path: str | Path) -> bool:
    """True when evals.require_signatures is true."""
    return str(_section(path, "evals").get("require_signatures")).lower() == "true"


def resolve_config_json(start_dir: str | Path | None = None) -> dict[str, Any]:
    """Typed view of the discovered config: path, values, defaults applied, unknown keys, findings."""
    path = config_path(start_dir)
    values, findings = load_config(path)
    present: set[str] = set()
    with contextlib.suppress(OSError):
        present = set(_entries(Path(path).read_text(encoding="utf-8", errors="replace"))) if path else present
    properties = _schema().get("properties", {})
    return {
        "path": path,
        "values": values,
        "defaults_applied": sorted(set(properties) - present),
        "unknown_keys": [f["key"] for f in findings if f["code"] == "config_unknown_key"],
        "findings": findings,
    }


def main() -> int:
    """Expose config discovery and content to command frontmatter."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("config-path", "resolve-config"))
    parser.add_argument("start_dir", nargs="?")
    parser.add_argument("--json", action="store_true", help="resolve-config: print the typed view as JSON")
    args = parser.parse_args()
    if args.json and args.operation == "resolve-config":
        print(json.dumps(resolve_config_json(args.start_dir), indent=2, sort_keys=True))
        return 0
    result = config_path(args.start_dir) if args.operation == "config-path" else resolve_config(args.start_dir)
    print(result, end="" if result.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
