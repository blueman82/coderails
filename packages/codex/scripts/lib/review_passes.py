"""Required-reviewer policy and the `passes` line of the SHA-bound review artifact.

The artifact body is: line 1 the unchanged v1 marker (the dashboard and the integrity gate parse only that line),
line 2 `<!-- coderails-review-passes v1 {"head_sha":..., "passes":[...]} -->`, then the posted summaries. Which passes
a diff needs comes only from policy/review_policy.json (`required`), never from the marker; a pass's verdict is
derived from the summary text (`verdict_from_summary`), never self-asserted: `parse` recomputes each pass's hash and
verdict from the posted sections and treats a mismatch as malformed. A pass proves a summary was posted for that
name, not that a reviewer wrote it or that the review was substantive.
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


def critical_lines(text: str) -> list[str]:
    """Stripped non-blank lines of the `## Critical` section ([] if the heading is absent)."""
    lines = text.splitlines()
    if "## Critical" not in lines:
        return []
    section: list[str] = []
    for line in lines[lines.index("## Critical") + 1 :]:
        if line.startswith("## "):
            break
        section.append(line.strip())
    return [line for line in section if line]


def verdict_from_summary(text: str) -> str:
    """`pass` iff the summary says `## No findings` or its Critical section is exactly the token `None`; else `fail`.

    Any other Critical line is a finding whatever its bullet style, so prose cannot hide one.
    """
    if "## No findings" in text.splitlines():
        headings = ("## Critical", "## Important", "## Suggestions")
        return "fail" if any(heading in text.splitlines() for heading in headings) else "pass"
    return "pass" if critical_lines(text) == ["None"] else "fail"


def validate_summary_text(text: str) -> None:
    """Require one unambiguous no-findings summary or all populated severity sections."""
    lines = text.splitlines()
    headings = ("## Critical", "## Important", "## Suggestions")
    if any(lines.count(heading) > 1 for heading in (*headings, "## No findings")):
        raise ValueError("duplicate summary heading")
    if any(line.startswith("<!-- coderails-review-") for line in lines):
        raise ValueError("review marker inside summary")
    if "## No findings" in lines:
        if any(heading in lines for heading in headings):
            raise ValueError('ambiguous — "## No findings" present alongside structured headings')
        return
    missing = [heading for heading in headings if heading not in lines]
    if missing:
        raise ValueError(f"missing required headings: {' '.join(missing)}")
    for heading in headings:
        populated = False
        for line in lines[lines.index(heading) + 1 :]:
            if line.startswith("## "):
                break
            if line.startswith("- ") or line == "None":
                populated = True
                break
        if not populated:
            raise ValueError(f'section "{heading}" has no bullet or None')
    critical = critical_lines(text)
    if "None" in critical and critical != ["None"]:
        raise ValueError('section "## Critical" says None and also lists other lines')


def summary_sha256(text: str) -> str:
    """Hex digest of the summary text a pass was derived from (line endings and outer whitespace are normalised)."""
    return hashlib.sha256(text.replace("\r\n", "\n").strip().encode()).hexdigest()


def tail(sections: list[tuple[str, str]]) -> str:
    """Artifact body after the two marker lines: the review-pr summary, then each other pass under its marker."""
    first, *rest = sections
    return "\n".join([first[1]] + [f"<!-- coderails-review-pass {name} -->\n{text}" for name, text in rest])


def _bound(rest: str, passes: Passes) -> bool:
    """Every pass names a posted section whose hash and derived verdict match what the line claims."""
    parts = re.split(r"^<!-- coderails-review-pass ([a-z][a-z0-9-]*) -->\r?\n", rest, flags=re.MULTILINE)
    names = ["review-pr", *parts[1::2]]
    declared = [p["name"] for p in passes]
    if "review-pr" not in declared or len(names) != len(set(names)) or len(declared) != len(set(declared)):
        return False
    texts = dict(zip(names, [parts[0], *parts[2::2]]))
    if set(texts) != {"review-pr", *declared}:
        return False
    try:
        for text in texts.values():
            validate_summary_text(text)
    except ValueError:
        return False
    return all(
        p["name"] in texts
        and p["summary_sha256"] == summary_sha256(texts[p["name"]])
        and p["verdict"] == verdict_from_summary(texts[p["name"]])
        for p in passes
    )


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
        and re.fullmatch(r"[a-z][a-z0-9-]*", entry["name"]) is not None
        and entry.get("verdict") in ("pass", "fail")
        and isinstance(entry.get("blocking"), bool)
        and isinstance(entry.get("summary_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", entry["summary_sha256"]) is not None
    )


def parse(body: str, pr: str, head_sha: str) -> Passes | None:
    """Passes for this PR head: [] only when the passes line is absent, None when present but invalid."""
    lines = body.splitlines()
    marker = next((i for i, line in enumerate(lines) if review_artifact.matches_marker(line, pr, head_sha)), -1)
    line = lines[marker + 1] if 0 <= marker < len(lines) - 1 else ""
    if not (line.startswith(PREFIX) and line.endswith(SUFFIX)):
        return None if line.startswith("<!-- coderails-review-passes") else []
    try:
        data = json.loads(line[len(PREFIX) : -len(SUFFIX)])
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(cast(dict[str, Any], data).get("passes"), list):
        return None
    if cast(dict[str, Any], data).get("head_sha") != head_sha:
        return None
    passes = cast(Passes, cast(dict[str, Any], data)["passes"])
    rest = "\n".join(lines[marker + 2 :])
    return passes if all(_valid(item) for item in passes) and _bound(rest, passes) else None
