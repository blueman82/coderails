"""Workflow and protected action policy over quote-aware invocation records."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import NamedTuple

from lib.argv_match import flags, git_invocation, git_prefix
from lib.destructive_patterns import git_output
from lib.shell_context import invocations

MERGE_SCRIPT = r"""(?:(?:bash|sh|python3?)\s+)?["']?(?:[^\s"']*/)?merge\.(?:py|sh)["']?(?:\s|$)"""


class Operation(NamedTuple):
    """One policy operation with its original Git read context and exact receipt command."""

    name: str
    segment: str
    cwd: str
    git_cwd: str
    prefix: list[str]


def operations(command: str, cwd: str = "") -> list[Operation]:
    """Classify every real operation, preserving invocation-local Git selection."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from scripts.lib.merge_target import has_noop_option

    found: list[Operation] = []
    for source, argv, where in invocations(command, cwd):
        name, directory, prefix = "", where, []
        call = git_invocation(argv, where)
        if call is not None:
            subcommand, directory, rest = call
            options = flags(rest)
            if options & {"--dry-run", "--help"}:
                continue
            if subcommand == "merge" and not options & {"--abort", "--continue", "--quit", "--skip"}:
                name = "git_merge"
            elif subcommand == "push":
                name = "git_push"
            prefix = git_prefix(argv, rest)
        elif argv[:3] in (["gh", "pr", "create"], ["gh", "pr", "merge"]):
            if has_noop_option(source):
                continue
            name = "create" if argv[2] == "create" else "merge"
        elif argv[:2] == ["gh", "api"] and any(re.search(r"/pulls/\d+/merge$", arg) for arg in argv[2:]):
            if "--help" not in flags(argv[2:]):
                name = "merge"
        elif re.search("^" + MERGE_SCRIPT, source):
            name = "merge"
        if name:
            found.append(Operation(name, unwrap(source), directory, where, prefix))
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
        for _, argv, where in invocations(call.segment, call.git_cwd):
            parsed = git_invocation(argv, where)
            if parsed and parsed[0] == "push":
                return any(
                    re.fullmatch(r"\+?(?:(?:[^:]*:)?refs/heads/|[^:]*:)?(?:main|master)", token)
                    for token in parsed[2]
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
