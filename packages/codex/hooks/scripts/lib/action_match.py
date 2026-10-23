"""Vendored subset of hooks/scripts/lib/pr_workflow_match.py (operation, targets_main, guarded_segments).

Parity-tested against the Claude copy in packages/tests/test_codex_action_authority.py: change both together.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from lib.destructive_patterns import git_output

MERGE_SCRIPT = r"""(?:(?:bash|sh|python3?)\s+)?["']?(?:[^\s"']*/)?merge\.(?:py|sh)["']?(?:\s|$)"""


def operation(command: str) -> tuple[str, str, str]:
    """Return guarded operation, matched segment, and optional Git target directory."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from scripts.lib.merge_target import has_noop_option

    for segment in re.split(r"&&|\|\||[;|&\n]", command):
        segment = segment.lstrip()
        if re.match(r"^git +merge +(--abort|--continue|--quit|--skip)(?:\s|$)", segment):
            continue
        if has_noop_option(segment) and not re.search("^" + MERGE_SCRIPT, segment):
            continue
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


def api_merge(segment: str) -> bool:
    """Recognize an API merge after its option values are consumed."""
    if not re.match(r"^gh\s+api(?:\s|$)", segment):
        return False
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from scripts.lib.merge_target import parse

    return parse(segment)[0].startswith("https://github.com/")


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
    Subshells restore their caller's cwd; brace groups keep their cwd changes.
    Wrappers are unwrapped (env/sudo/time prefixes, subshell and brace groups, `bash -c '...'`, `gh api .../merge`).
    Still unmatched: eval, xargs, aliases, functions, scripts that push. ponytail: regex, not a shell parser.
    """
    found: list[tuple[str, str, str]] = []
    subshells: list[str] = []
    masked = _SHELL_C.sub(lambda inner: " " * len(inner[0]), command)
    cursor = 0
    for boundary in re.finditer(r"&&|\|\||[;|&\n]|$", masked):
        segment = command[cursor : boundary.start()].strip()
        cursor = boundary.end()
        leading = segment[: len(segment) - len(segment.lstrip("({ "))]
        subshells.extend([cwd] * leading.count("("))
        closes = segment[len(segment.rstrip(")} ")) :].count(")")
        segment = unwrap(segment)
        if move := re.match(r"^cd\s+(\S+)$", segment):
            cwd = os.path.normpath(os.path.join(cwd, os.path.expanduser(move[1].strip("\"'"))))
        else:
            for inner in _SHELL_C.finditer(segment):
                found.extend(guarded_segments(inner[2], cwd))
            segment = _SHELL_C.sub(" ", segment)
            if api_merge(segment):
                found.append(("merge", segment, cwd))
            else:
                name, matched, target = operation(segment)
                if name in {"merge", "git_push"} and targets_main(segment, cwd, target, name):
                    found.append((name, matched, cwd))
        for _ in range(closes):
            if subshells:
                cwd = subshells.pop()
    return found
