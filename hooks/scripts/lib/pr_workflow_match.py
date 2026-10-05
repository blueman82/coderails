"""Match guarded Git operations and native Claude review invocations."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, cast

from .destructive_patterns import git_output
from .discipline_common import tool_uses

MERGE_SCRIPT = r"""(?:(?:bash|sh|python3?)\s+)?["']?(?:[^\s"']*/)?merge\.(?:py|sh)["']?(?:\s|$)"""


def operation(command: str) -> tuple[str, str, str]:
    """Return guarded operation, matched segment, and optional Git target directory."""
    if re.search(r"(^|[^-a-zA-Z0-9])(--dry-run|--help)([^-a-zA-Z0-9]|$)", command) and not re.search(
        r"(^|[;&|\s])" + MERGE_SCRIPT, command
    ):
        return "", "", ""
    if re.search(r"\bgit +merge +(--abort|--continue|--quit|--skip)\b", command):
        return "", "", ""
    for segment in re.split(r"&&|\|\||[;|&\n]", command):
        segment = segment.lstrip()
        for pattern, name in (
            (r"^gh\s+pr\s+create(?:\s|$)", "create"),
            (r"^gh\s+pr\s+merge(?:\s|$)", "merge"),
            (r"^git\s+merge(?:\s|$)", "git_merge"),
            (r"^git\s+push(?:\s|$)", "git_push"),
            ("^" + MERGE_SCRIPT, "merge"),
        ):
            if re.search(pattern, segment):
                return name, segment, ""
        if match := re.search(r"^git\s+-C\s+(\S+)\s+(merge|push)(?:\s|$)", segment):
            return f"git_{match[2]}", segment, match[1]
    return "", "", ""


def targets_main(command: str, cwd: str, target: str, name: str) -> bool:
    """Check both current branch and explicitly named protected push destinations."""
    if name not in {"git_merge", "git_push"}:
        return True
    match = re.match(r"^\s*cd\s+(\S+)\s*(&&|;)", command)
    target = target or (match[1] if match else "")
    directory = str(Path(cwd) / target) if target and not target.startswith("/") else target or cwd
    branch = git_output(directory, "branch", "--show-current") or git_output(cwd, "branch", "--show-current")
    if branch in {"main", "master"}:
        return True
    if name != "git_push":
        return False
    if re.search(r":(refs/heads/)?(main|master)([\s;&|)]|$)", command):
        return True
    match = re.search(r"\bgit(?:\s+-C\s+\S+)?\s+push\s+(.*)", command)
    return bool(match and re.search(r"(^|\s)\+?(refs/heads/)?(main|master)([\s;&|)]|$)", match[1]))


_WRAPPER = re.compile(r"^(?:[A-Za-z_]\w*=\S*|env|sudo|time|command|exec|nohup)\s+")
_SHELL_C = re.compile(r"\b(?:bash|sh|zsh)\s+-\w*c\s+([\"'])(.*?)\1")
_API_MERGE = re.compile(r"^gh\s+api\s+\S*/pulls/\d+/merge(?:\s|$)")


def unwrap(segment: str) -> str:
    """Strip grouping, env assignments and env/sudo/time/command/exec/nohup prefixes to the command itself."""
    segment = segment.strip().lstrip("({ ").rstrip(")} ")
    while match := _WRAPPER.match(segment):
        segment = segment[match.end() :].lstrip()
    return segment


def guarded_segments(command: str, cwd: str) -> list[tuple[str, str, str]]:
    """Every guarded (merge | git_push to main) segment as (operation, segment, effective cwd).

    A leading `cd <dir>` segment moves the effective cwd for the segments after it, so the receipt hash binds the
    directory the operation really runs in. Each segment is matched on its own: a chain is one guard per segment.
    Wrappers are unwrapped (env/sudo/time prefixes, subshell and brace groups, `bash -c '...'`, `gh api .../merge`).
    Still unmatched: eval, xargs, aliases, functions, scripts that push. ponytail: regex, not a shell parser.
    """
    found: list[tuple[str, str, str]] = []
    for inner in _SHELL_C.finditer(command):
        found.extend(guarded_segments(inner[2], cwd))
    command = _SHELL_C.sub(" ", command)
    for segment in re.split(r"&&|\|\||[;|&\n]", command):
        segment = unwrap(segment)
        if move := re.match(r"^cd\s+(\S+)$", segment):
            cwd = os.path.normpath(os.path.join(cwd, os.path.expanduser(move[1].strip("\"'"))))
            continue
        if _API_MERGE.match(segment):
            found.append(("merge", segment, cwd))
            continue
        name, matched, target = operation(segment)
        if name in {"merge", "git_push"} and targets_main(segment, cwd, target, name):
            found.append((name, matched, cwd))
    return found


def pr_number(segment: str) -> str:
    """Read the explicit PR argument while excluding option tokens."""
    match = re.search(r"gh\s+pr\s+merge(.*)", segment)
    arguments = match[1] if match else re.sub(r"^.*?merge\.(?:sh|py)", "", segment)
    return next((token.strip("\"'") for token in arguments.split() if re.match(r"^[0-9]", token.strip("\"'"))), "")


def transcript_entries(paths: list[str]) -> list[dict[str, Any]]:
    """Read complete transcripts; a malformed transcript cannot establish a prerequisite."""
    result: list[dict[str, Any]] = []
    for path in paths:
        try:
            entries = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
            if all(isinstance(entry, dict) for entry in entries):
                result.extend(entries)
        except (OSError, ValueError):
            continue
    return result


def step_found(entries: list[dict[str, Any]], name: str, number: str) -> bool:
    """Verify native Skill evidence, consuming raw-main-merge review evidence once."""
    if name == "git_merge":
        entries = sorted(entries, key=lambda entry: str(entry.get("timestamp") or ""))
        last = max(
            (
                index
                for index, entry in enumerate(entries)
                for tool in tool_uses(entry)
                if tool.get("name") == "Bash"
                and isinstance(tool.get("input"), dict)
                and re.search(r"\bgit\s+merge\b", str(tool["input"].get("command") or ""))
            ),
            default=-1,
        )
        entries = entries[last + 1 :]
    for entry in entries:
        for tool in tool_uses(entry):
            data = tool.get("input")
            if not isinstance(data, dict):
                continue
            skill = str(cast(dict[str, Any], data).get("skill") or "")
            if name == "create":
                if tool.get("name") == "Skill" and re.search(r"(^|:)push$", skill):
                    return True
                if tool.get("name") == "Bash" and re.search(
                    r"push\.(?:sh|py)", str(cast(dict[str, Any], data).get("command") or "")
                ):
                    return True
            elif tool.get("name") == "Skill" and skill.endswith("review-pr"):
                if (
                    name != "merge"
                    or not number
                    or re.search(
                        r"^" + re.escape(number) + r"([^0-9]|$)", str(cast(dict[str, Any], data).get("args") or "")
                    )
                ):
                    return True
    return False
