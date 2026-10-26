"""Validate posted review and eval artifacts as data, without running PR commands."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from integrity_http import JsonObject  # noqa: E402

from scripts.lib.eval_integrity import IntegrityError as EvalIntegrityError  # noqa: E402
from scripts.lib.eval_integrity import integrity_version, signed_freeze_timing, verify_suite  # noqa: E402
from scripts.lib.eval_signing import VERIFIED  # noqa: E402


def review_valid(body: str, number: int, sha: str) -> bool:
    """Require one exact marker and a structurally valid reviewer summary."""
    marker = f"<!-- coderails-review-summary v1 pr={number} head_sha={sha} -->"
    lines = body.splitlines()
    if len(lines) < 2 or lines[0] != marker:
        return False
    start = 1
    if lines[1].startswith("<!-- coderails-compat-findings"):
        compat = re.fullmatch(
            rf"<!-- coderails-compat-findings v1 pr={number} head_sha={re.escape(sha)} "
            r"count=(0|[1-9][0-9]{0,8}) disposition=(clean-break|preserve-compat) -->",
            lines[1],
        )
        if compat is None:
            return False
        count = int(compat[1])
        if (compat[2] == "clean-break" and count > 0) or ("## No findings" in lines[2:] and count > 0):
            return False
        start = 2
    summary = [line for line in lines[start:] if line.strip()]
    if summary == ["## No findings"]:
        return True
    if any("coderails-compat-findings" in line for line in summary):
        return False
    headings = ("## Critical", "## Important", "## Suggestions")
    if [line for line in summary if line.startswith("## ")] != list(headings):
        return False
    for index, heading in enumerate(headings):
        start = summary.index(heading) + 1
        end = summary.index(headings[index + 1]) if index < 2 else len(summary)
        if not any(line == "None" or line.startswith("- ") for line in summary[start:end]):
            return False
    return True


def _real_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _bounded_json_depth(value: str, limit: int = 100) -> bool:
    """Refuse deeply nested owner JSON before runtime-specific parser limits differ."""
    depth = 0
    quoted = False
    escaped = False
    for char in value:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > limit:
                return False
        elif char in "]}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not quoted


def _eval_valid(item: object, level: int) -> bool:
    if not isinstance(item, dict):
        return False
    item = cast(JsonObject, item)
    if not all(_text(item.get(key)) for key in ("id", "priority", "mode", "status", "assert", "expected")):
        return False
    if item["priority"] not in ("P0", "P1") or item["status"] not in ("pass", "fail", "pending"):
        return False
    if item["priority"] == "P0" and (item["status"] != "pass" or not _text(item.get("evidence"))):
        return False
    if item["mode"] == "agent-run":
        return _text(item.get("verifier_instruction"))
    if item["mode"] != "scripted" or not _text(item.get("cmd")):
        return False
    if level == 0:
        return True
    if not _text(item.get("negative_control")) or item["cmd"].strip() == item["negative_control"].strip():
        return False
    smoke = item.get("smoke")
    if not isinstance(smoke, dict):
        return False
    smoke = cast(JsonObject, smoke)
    command_exit, control_exit = smoke.get("cmd_exit"), smoke.get("negative_control_exit")
    if not isinstance(command_exit, int) or isinstance(command_exit, bool):
        return False
    if not isinstance(control_exit, int) or isinstance(control_exit, bool):
        return False
    return not (
        command_exit in (126, 127) or command_exit >= 128 or control_exit in (0, 126, 127) or control_exit >= 128
    )


def eval_valid(body: str, number: int, sha: str) -> bool:
    """Check marker, current head, frozen oracle and recorded outcomes as data."""
    if len(body) > 262144:
        return False
    lines = body.splitlines()
    if not lines:
        return False
    marker = re.fullmatch(
        rf"<!-- coderails-eval-summary v1 pr={number} head_sha={sha} result=GO verification_level=([0-2]) -->",
        lines[0],
    )
    if marker is None or len(re.findall(r"^```json\s*$", body, re.MULTILINE)) != 1:
        return False
    block = re.search(r"^```json\s*\n(.*?)^```\s*$", body, re.MULTILINE | re.DOTALL)
    if block is None:
        return False
    if not _bounded_json_depth(block[1]):
        return False
    try:
        data: object = json.loads(block[1])
    except (RecursionError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    data = cast(JsonObject, data)
    if not _real_int(data.get("schema_version")) or data["schema_version"] != 1 or data.get("scope") != "pr":
        return False
    level = data.get("verification_level")
    if not isinstance(level, int) or isinstance(level, bool) or str(level) != marker[1] or level < 1:
        return False
    if not all(_text(data.get(key)) for key in ("task_ref", "verification_justification", "frozen_at")):
        return False
    if data.get("head_sha") != sha or not re.fullmatch(r"[0-9a-f]{40}", str(data.get("frozen_sha") or "")):
        return False
    try:
        datetime.fromisoformat(data["frozen_at"].replace("Z", "+00:00"))
    except ValueError:
        return False
    entries = data.get("evals")
    if not isinstance(entries, list):
        return False
    entries = cast(list[object], entries)
    if not entries or not any(
        isinstance(item, dict) and cast(JsonObject, item).get("priority") == "P0" for item in entries
    ):
        return False
    ids = [cast(JsonObject, item).get("id") for item in entries if isinstance(item, dict)]
    if len(ids) != len(entries) or not all(_text(identifier) for identifier in ids):
        return False
    if len(set(cast(list[str], ids))) != len(ids) or not all(_eval_valid(item, level) for item in entries):
        return False
    if not _text(data.get("frozen_hash")):
        return False
    grading = data.get("grading")
    if isinstance(grading, dict):
        chain_len = cast(JsonObject, grading).get("chain_len")
        if isinstance(chain_len, int) and not isinstance(chain_len, bool) and chain_len < 0:
            return False
    try:
        if verify_suite(data, trust_signer=False) != VERIFIED:
            return False
        if integrity_version(data) == 1 and not signed_freeze_timing(
            data, str(data["frozen_sha"]), str(data["frozen_at"]), "unverifiable", trust_signer=False
        ):
            return False
    except (EvalIntegrityError, IndexError, RecursionError, TypeError, ValueError):
        return False
    return data.get("result") in (None, "GO")
