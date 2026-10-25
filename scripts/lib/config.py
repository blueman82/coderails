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
            return _without_comment(match[1]).strip().strip("\"'")
    return ""


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config.schema.json"
KEY_LINE = re.compile(r"(\s*)([A-Za-z_][\w-]*):[ \t]*(.*)")
NULLS = frozenset({"null", "~"})
NUMERIC_SCALAR = re.compile(
    r"[-+]?(?:0[xX][0-9a-fA-F_]+|0[oO][0-7_]+|0[bB][01_]+|(?:[0-9][0-9_]*(?:\.[0-9_]*)?|\.[0-9_]+)(?:[eE][-+]?[0-9_]+)?)"
)


def _without_comment(value: str) -> str:
    """Remove a YAML comment while keeping hashes in quoted or attached scalars."""
    quote = ""
    index = 0
    while index < len(value):
        char = value[index]
        if quote == '"' and char == "\\":
            index += 2
            continue
        if quote == "'" and char == "'" and value[index : index + 2] == "''":
            index += 2
            continue
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'" and not value[:index].strip():
            quote = char
        elif char == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
        index += 1
    return value


def _scalar(value: str) -> dict[str, Any]:
    """Keep quote marks as type evidence while removing the enclosing pair."""
    raw = _without_comment(value).strip()
    quoted = len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0]
    return {"raw": raw[1:-1] if quoted else raw, "quoted": quoted}


def _schema() -> dict[str, Any]:
    """Read the typed-config schema or report that typed resolution is unavailable."""
    try:
        data: Any = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("config_schema_unreadable") from error
    if not isinstance(data, dict):
        raise ValueError("config_schema_unreadable")
    schema = cast("dict[str, Any]", data)
    if not isinstance(schema.get("properties"), dict):
        raise ValueError("config_schema_unreadable")
    return schema


def _entries(text: str, findings: list[dict[str, str]] | None = None) -> dict[str, dict[str, Any]]:
    """Parse the single-level grammar plus one nested level: {key: {raw, items, children}}.

    A line that fits no branch or repeats a key at its level is reported (config_unparseable_line,
    config_duplicate_key; key "line N") so malformed syntax cannot silently drop a setting.
    """
    found = findings if findings is not None else []
    top: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    current_top = ""
    indent = None

    def flag(code: str, key: str) -> None:
        found.append({"code": code, "key": key, "hint": ""})

    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        where = f"line {number}"
        match = KEY_LINE.fullmatch(line)
        if not line[0].isspace():
            current = {"raw": "", "items": [], "children": {}} if match else None
            current_top = match[2] if match else ""
            indent = None
            if match and current is not None:
                current.update(_scalar(match[3]))
                if match[2] in top:
                    flag("config_duplicate_key", match[2])
                top[match[2]] = current
            else:
                flag("config_unparseable_line", where)
        elif current is not None and stripped.startswith("- "):
            current["items"].append(_without_comment(stripped[2:]).strip().strip("\"'"))
        elif current is not None and match:
            indent = len(match[1]) if indent is None else indent
            kids = cast("list[dict[str, Any]]", list(current["children"].values()))
            if len(match[1]) > indent and current_top == "jira" and kids and kids[-1]["raw"] == "":
                continue  # Jira's nested mapping is deliberately untyped.
            if len(match[1]) != indent:
                flag("config_unparseable_line", where)
            else:
                if match[2] in current["children"]:
                    flag("config_duplicate_key", f"{match[2]} ({where})")
                current["children"][match[2]] = _scalar(match[3])
        else:
            flag("config_unparseable_line", where)
    return top


def _coerce(entry: dict[str, Any], spec: dict[str, Any]) -> tuple[Any, bool]:
    """Return (value, ok); a value that fits no allowed type is returned raw with ok False."""
    types = spec.get("type", [])
    raw = entry["raw"]
    if entry.get("children") and "object" in types:
        return {key: child["raw"] for key, child in entry["children"].items()}, True
    if entry.get("items") and "array" in types:
        return list(entry["items"]), True
    if entry.get("quoted"):
        return raw, "string" in types
    if raw == "":
        return None, "null" in types and not (entry.get("items") or entry.get("children"))
    if raw in NULLS:
        return (None, True) if "null" in types else (raw, False)
    if raw.lower() in ("true", "false"):
        return (raw.lower() == "true", True) if "boolean" in types else (raw, False)
    if NUMERIC_SCALAR.fullmatch(raw):
        return (int(raw), True) if "integer" in types and re.fullmatch(r"-?[0-9]+", raw) else (raw, False)
    if raw.startswith("[") and raw.endswith("]"):
        items = [item.strip().strip("\"'") for item in raw[1:-1].split(",") if item.strip()]
        return (items, True) if "array" in types else (raw, False)
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
        if not ok or (isinstance(value, str) and value not in spec.get("enum", [value])):
            code = "config_bad_value" if ok else "config_bad_type"
            hint = _hint(value, dict.fromkeys(spec["enum"])) if ok else "/".join(spec["type"])
            findings.append({"code": code, "key": prefix + key, "hint": hint})
        elif isinstance(value, dict) and spec.get("properties"):
            value = _typed(entry["children"], spec["properties"], prefix + key + ".", findings)
        values[key] = value
    for key, spec in properties.items():
        if key not in values:
            values[key] = copy.deepcopy(spec.get("default"))
    return values


def load_config(path: str | Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Parse path against config.schema.json: (typed values with defaults, reason-coded findings). Never raises."""
    findings: list[dict[str, str]] = []
    properties: dict[str, Any]
    try:
        properties = cast("dict[str, Any]", _schema()["properties"])
    except (OSError, ValueError, KeyError, TypeError):
        properties = {}
        findings.append({"code": "config_schema_unreadable", "key": "", "hint": ""})
    text = ""
    if path:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, ValueError):
            findings.append({"code": "config_unreadable", "key": "", "hint": ""})
    entries = _entries(text, findings)
    return _typed(entries, properties, "", findings), findings


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


def _section(path: str | Path, key: str) -> dict[str, Any]:
    """One typed nested section of the config at path, or {}."""
    value = settings(path).get(key)
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def integrity_enabled(path: str | Path) -> bool:
    """Keep legacy machine-user gates active until explicit config migration."""
    settings = _section(path, "integrity_review")
    legacy = settings.get("machine_user")
    return settings.get("enabled") is True or (isinstance(legacy, str) and bool(legacy))


def integrity_status_login(path: str | Path) -> str:
    """Trust the old login until enabled=true selects the Actions bot."""
    settings = _section(path, "integrity_review")
    legacy = settings.get("machine_user")
    if settings.get("enabled") is not True and isinstance(legacy, str) and legacy:
        return legacy
    return "github-actions[bot]"


def require_signatures(path: str | Path) -> bool:
    """True unless evals.require_signatures is explicitly false (a config with findings stays ON; no path = inert)."""
    if not path:
        return False
    values, findings = load_config(path)
    report_findings(findings)
    # An explicit false is the only OFF; null, a bad type or a rejected config keep signing ON (fail closed).
    evals = cast("dict[str, Any]", values.get("evals") or {})
    return bool(findings) or evals.get("require_signatures") is not False


def resolve_config_json(start_dir: str | Path | None = None) -> dict[str, Any]:
    """Typed view of the discovered config: path, values, defaults applied, unknown keys, findings."""
    path = config_path(start_dir)
    values, findings = load_config(path)
    present: set[str] = set()
    with contextlib.suppress(OSError):
        present = set(_entries(Path(path).read_text(encoding="utf-8", errors="replace"))) if path else present
    properties: dict[str, Any]
    try:
        properties = cast("dict[str, Any]", _schema()["properties"])
    except (OSError, ValueError, KeyError, TypeError):
        properties = {}
    return {
        "path": path,
        "values": values,
        "defaults_applied": sorted(set(properties) - present),
        "unknown_keys": [f["key"] for f in findings if f["code"] == "config_unknown_key"],
        "findings": findings,
        "valid": not findings,
    }


def main() -> int:
    """Expose config discovery and content to command frontmatter."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("config-path", "resolve-config"))
    parser.add_argument("start_dir", nargs="?")
    parser.add_argument("--json", action="store_true", help="resolve-config: print the typed view as JSON")
    args = parser.parse_args()
    if args.json and args.operation == "resolve-config":
        data = resolve_config_json(args.start_dir)
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0 if data["valid"] else 1
    result = config_path(args.start_dir) if args.operation == "config-path" else resolve_config(args.start_dir)
    print(result, end="" if result.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
