"""Workflow and protected action policy over quote-aware invocation records."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, NamedTuple, cast

from .argv_match import flags, git_invocation, git_prefix
from .destructive_patterns import git_output
from .discipline_common import tool_uses
from .shell_context import invocations

MERGE_SCRIPTS = {"merge.py", "merge.sh"}


class Operation(NamedTuple):
    """One policy operation with its original Git read context and exact receipt command."""

    name: str
    segment: str
    cwd: str
    git_cwd: str
    prefix: list[str]
    git_args: list[str]


def operations(command: str, cwd: str = "") -> list[Operation]:
    """Classify every real operation, preserving invocation-local Git selection."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from scripts.lib.merge_target import has_noop_option

    found: list[Operation] = []
    for source, argv, where in invocations(command, cwd):
        name, directory, prefix, git_args = "", where, [], []
        call = git_invocation(argv, where)
        if call is not None:
            subcommand, directory, rest = call
            options = flags(rest, "mFsX" if subcommand == "merge" else "")
            if options & {"--dry-run", "--help"}:
                continue
            if subcommand == "merge" and not options & {"--abort", "--continue", "--quit", "--skip"}:
                name = "git_merge"
            elif subcommand == "push":
                name = "git_push"
            prefix = git_prefix(argv, rest)
            git_args = rest
        elif argv[:3] in (["gh", "pr", "create"], ["gh", "pr", "merge"]):
            if has_noop_option(source):
                continue
            name = "create" if argv[2] == "create" else "merge"
        elif argv[:2] == ["gh", "api"] and any(re.search(r"/pulls/\d+/merge$", arg) for arg in argv[2:]):
            if "--help" not in flags(argv[2:]):
                name = "merge"
        elif Path(argv[0]).name in MERGE_SCRIPTS or (
            len(argv) > 1 and argv[0] in {"bash", "sh", "python", "python3"} and Path(argv[1]).name in MERGE_SCRIPTS
        ):
            name = "merge"
        if name:
            found.append(Operation(name, unwrap(source), directory, where, prefix, git_args))
    return found


def operation(command: str) -> tuple[str, str, str]:
    """The current first-operation API, projected from the maintained operation records."""
    found = operations(command)
    return (found[0].name, found[0].segment, found[0].cwd) if found else ("", "", "")


def repository(call: Operation) -> str:
    """Resolve the selected Git worktree for repository configuration reads."""
    return git_output(call.git_cwd, *call.prefix, "rev-parse", "--show-toplevel") or call.cwd


def targets_main(call: Operation) -> bool:
    """Recognize the selected branch or an explicit protected push destination."""
    if call.name not in {"git_merge", "git_push"}:
        return True
    if git_output(call.git_cwd, *call.prefix, "branch", "--show-current") in {"main", "master"}:
        return True
    if call.name == "git_push":
        return any(
            re.fullmatch(r"\+?(?:(?:[^:]*:)?refs/heads/|[^:]*:)?(?:main|master)", token)
            for token in call.git_args
            if not token.startswith("-")
        )
    return False


_WRAPPER = re.compile(r"^(?:[A-Za-z_]\w*=\S*|env|sudo|time|command|exec|nohup)\s+")


def unwrap(segment: str) -> str:
    """Strip the established simple wrapper and group prefixes without changing receipt bytes."""
    segment = segment.strip().lstrip("({ ").rstrip(")} ")
    while match := _WRAPPER.match(segment):
        segment = segment[match.end() :].lstrip()
    return segment


def guarded_operations(command: str, cwd: str) -> list[Operation]:
    """The guarded operations retain selection metadata for their consumer reads."""
    return [call for call in operations(command, cwd) if call.name in {"merge", "git_push"} and targets_main(call)]


def guarded_segments(command: str, cwd: str) -> list[tuple[str, str, str]]:
    """The current exact-command/cwd API over the same guarded operation records."""
    return [(call.name, call.segment, call.cwd) for call in guarded_operations(command, cwd)]


def pr_number(segment: str) -> str:
    """The merge target: a number, URL or branch as written, "" for none, "?" when unresolvable (-R, two targets)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    # Import at use time so a Claude lookup cannot bind the independently installed Codex scripts package.
    from scripts.lib import merge_target

    return merge_target.parse(segment)[0]


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
                and any(call.name == "git_merge" for call in operations(str(tool["input"].get("command") or "")))
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
