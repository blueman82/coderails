"""Required-reviewer policy and the `passes` line of the SHA-bound review artifact.

The artifact body is: line 1 the unchanged v1 marker (the dashboard and the integrity gate parse only that line),
line 2 `<!-- coderails-review-passes v1 {"head_sha":..., "passes":[...]} -->`, then the posted summaries. Which passes
a diff needs comes only from policy/review_policy.json (`required`), never from the marker; a pass's verdict is
derived from the validated summary text (`verdict_from_summary`), never self-asserted. A pass proves a validated
summary was posted for that name, not that the review was substantive.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, cast

from . import review_artifact

POLICY = Path(__file__).resolve().parents[2] / "policy" / "review_policy.json"
PREFIX = "<!-- coderails-review-passes v1 "
SUFFIX = " -->"
Passes = list[dict[str, Any]]
Changes = list[tuple[str, list[str]]]


def load_policy(path: str | Path = POLICY) -> dict[str, Any]:
    """Return the policy; any missing, torn or ill-shaped file raises ValueError("review_policy_unreadable")."""
    from . import manifest_policy  # lazy: manifest_policy imports git_common, which imports this module

    data = manifest_policy.load_json(path)
    rules = data.get("rules") if data else None
    ok = data is not None and _texts(data.get("always")) is not None and isinstance(rules, list)
    for rule in cast(list[object], rules) if ok else []:
        fields = cast(dict[str, Any], rule) if isinstance(rule, dict) else {}
        ok = ok and isinstance(fields.get("pass"), str) and _texts(fields.get("paths")) is not None
    if data is None or not ok:
        raise ValueError("review_policy_unreadable")
    return data


def _texts(value: object) -> list[str] | None:
    """The value when it is a list of strings, else None."""
    items = cast(list[object], value) if isinstance(value, list) else None
    return cast(list[str], items) if items is not None and all(isinstance(x, str) for x in items) else None


def required(changes: Changes, policy: dict[str, Any]) -> list[str]:
    """Pass names the diff needs: the always-required ones, then each rule whose paths match (renames: both sides)."""
    from . import manifest_policy  # lazy, see load_policy

    names: list[str] = list(policy["always"])
    paths = [p for _, group in changes for p in group]
    for rule in policy["rules"]:
        if rule["pass"] not in names and any(manifest_policy.matches(p, rule["paths"]) for p in paths):
            names.append(rule["pass"])
    return names


def verdict_from_summary(text: str) -> str:
    """`pass` iff the summary says `## No findings` or its Critical section holds no bullet; else `fail`."""
    lines = text.splitlines()
    if "## No findings" in lines:
        return "pass"
    section: list[str] = []
    if "## Critical" in lines:
        for line in lines[lines.index("## Critical") + 1 :]:
            if line.startswith("## "):
                break
            section.append(line)
    return "fail" if any(line.startswith("- ") for line in section) or "## Critical" not in lines else "pass"


def summary_sha256(text: str) -> str:
    """Hex digest of the summary text a pass was derived from."""
    return hashlib.sha256(text.encode()).hexdigest()


def render(head_sha: str, passes: Passes) -> str:
    """The second marker line for a head and its passes."""
    return PREFIX + json.dumps({"head_sha": head_sha, "passes": passes}, sort_keys=True) + SUFFIX


def _valid(item: object) -> bool:
    """One passes[] entry has the four typed fields."""
    if not isinstance(item, dict):
        return False
    entry = cast(dict[str, Any], item)
    return (
        isinstance(entry.get("name"), str)
        and bool(entry["name"])
        and entry.get("verdict") in ("pass", "fail")
        and isinstance(entry.get("blocking"), bool)
        and isinstance(entry.get("summary_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", entry["summary_sha256"]) is not None
    )


def parse(body: str, pr: str, head_sha: str) -> Passes | None:
    """Passes of the artifact for this PR head: [] when there is no line or it names another head, None if malformed."""
    lines = body.splitlines()
    marker = next((i for i, line in enumerate(lines) if review_artifact.matches_marker(line, pr, head_sha)), -1)
    line = lines[marker + 1] if 0 <= marker < len(lines) - 1 else ""
    if not (line.startswith(PREFIX) and line.endswith(SUFFIX)):
        return []
    try:
        data = json.loads(line[len(PREFIX) : -len(SUFFIX)])
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(cast(dict[str, Any], data).get("passes"), list):
        return None
    if cast(dict[str, Any], data).get("head_sha") != head_sha:
        return []
    passes = cast(Passes, cast(dict[str, Any], data)["passes"])
    return passes if all(_valid(item) for item in passes) else None
