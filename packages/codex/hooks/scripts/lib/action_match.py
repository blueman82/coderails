"""Vendored subset of hooks/scripts/lib/pr_workflow_match.py (operation, targets_main, guarded_segments).

Parity-tested against the Claude copy in packages/tests/test_codex_action_authority.py: change both together.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from lib.destructive_patterns import git_output

MERGE_SCRIPT = r"""(?:(?:bash|sh|python3?)\s+)?["']?(?:[^\s"']*/)?merge\.(?:py|sh)["']?(?:\s|$)"""
_GIT_OPT = r"(?:-C\s+\S+|-c\s+\S+|--[\w-]+=\S+|--(?:git-dir|work-tree|namespace|exec-path)\s+\S+|--[\w-]+|-[pP])"
_GIT = re.compile(r"^git((?:\s+" + _GIT_OPT + r")*)\s+(merge|push)(?:\s|$)")


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
            ("^" + MERGE_SCRIPT, "merge"),
        ):
            if re.search(pattern, segment):
                return name, segment, ""
        if match := _GIT.match(segment):  # git global options (-c, -C, --git-dir, --no-pager ...) before the subcommand
            directory = re.search(r"-C\s+(\S+)", match[1])
            return f"git_{match[2]}", segment, directory[1] if directory else ""
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
    match = re.search(r"\bgit\b[^;&|]*?\bpush\s+(.*)", command)
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
    for raw in re.split(r"&&|\|\||[;|&\n]", command):
        segment = unwrap(raw)
        # An env assignment (GIT_DIR=, GH_REPO=, GIT_CONFIG_*=) can retarget the action: keep the prefix in the
        # segment so action_binding refuses it (binding None -> denied) instead of binding the approved repo.
        stripped = raw.strip().lstrip("({ ")
        tainted = bool(re.search(r"(?:^|\s)[A-Za-z_]\w*=", stripped[: max(stripped.find(segment), 0)]))
        if move := re.match(r"^cd\s+(\S+)$", segment):
            cwd = os.path.normpath(os.path.join(cwd, os.path.expanduser(move[1].strip("\"'"))))
            continue
        if _API_MERGE.match(segment):
            found.append(("merge", stripped.rstrip(")} ") if tainted else segment, cwd))
            continue
        name, matched, target = operation(segment)
        if name in {"merge", "git_push"} and targets_main(segment, cwd, target, name):
            found.append((name, stripped.rstrip(")} ") if tainted else matched, cwd))
    return found


_MUTATOR = re.compile(
    r"^git(?:\s+" + _GIT_OPT + r")*\s+(?:branch|reset|checkout|switch|update-ref|commit|merge|rebase|cherry-pick|pull"
    r"|fetch|tag|symbolic-ref|revert|am|replace|config|remote|restore|stash)(?:\s|$)"
)


def state_mutated_before_guard(command: str) -> bool:
    """True when a guarded segment follows a segment that can move a ref, HEAD or the remote config.

    The receipt binds the sha/ref/remote as they are when the hook runs, so `git branch -f x <sha> && git push origin
    x:main` would push a different sha than the one approved. Such a chain is refused; run the steps separately.
    Scripts, aliases and functions that mutate are not seen. ponytail: regex, not a shell parser.
    """
    mutated = False
    for inner in _SHELL_C.finditer(command):
        mutated = mutated or state_mutated_before_guard(inner[2])
    for raw in re.split(r"&&|\|\||[;|&\n]", _SHELL_C.sub(" ", command)):
        segment = unwrap(raw)
        if mutated and (_API_MERGE.match(segment) or operation(segment)[0] in {"merge", "git_push"}):
            return True
        mutated = mutated or bool(_MUTATOR.match(segment))
    return False
