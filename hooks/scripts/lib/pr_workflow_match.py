"""Match guarded Git operations and native Claude review invocations."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any, NamedTuple, cast

from . import argv_match
from .destructive_patterns import git_output
from .discipline_common import tool_uses
from .shell_context import invocations

MERGE_SCRIPT = r"""(?:(?:bash|sh|python3?)\s+)?["']?(?:[^\s"']*/)?merge\.(?:py|sh)["']?(?:\s|$)"""
_GIT_OPT = r"(?:-C\s+\S+|-c\s+\S+|--[\w-]+=\S+|--(?:git-dir|work-tree|namespace|exec-path)\s+\S+|--[\w-]+|-[pP])"
_GIT = re.compile(r"^git((?:\s+" + _GIT_OPT + r")*)\s+(merge|push)(?:\s|$)")
UNBINDABLE = "CODERAILS_UNBINDABLE=1 "


class Operation(NamedTuple):
    """One command with its exact source and Git selection context."""

    name: str
    segment: str
    cwd: str
    git_cwd: str
    prefix: list[str]
    git_args: list[str]
    selected_cwd: str


def _gh_args(argv: list[str]) -> list[str]:
    """Skip GitHub CLI global repository options before the command."""
    if argv[:1] != ["gh"]:
        return []
    index = 1
    while index < len(argv):
        token = argv[index]
        if token in {"-R", "--repo", "--hostname"}:
            index += 2
        elif token.startswith(("--repo=", "--hostname=")):
            index += 1
        else:
            break
    return argv[index:]


def operations(command: str, cwd: str = "") -> list[Operation]:
    """Classify each invoked action; keep unknown bindings visibly unbindable."""
    cwd = cwd or os.getcwd()
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from scripts.lib.merge_target import has_noop_option

    found: list[Operation] = []
    for source, argv, where in invocations(command, cwd):
        name, prefix, git_args, selected = "", [], [], where
        gh_args = _gh_args(argv)
        call = argv_match.git_invocation(argv, where)
        if call is not None:
            subcommand, selected, rest = call
            options = argv_match.flags(rest, "mFsX" if subcommand == "merge" else "")
            if options & {"--dry-run", "--help"}:
                continue
            if subcommand == "merge" and not options & {"--abort", "--continue", "--quit", "--skip"}:
                name = "git_merge"
            elif subcommand == "push":
                name = "git_push"
            prefix = argv_match.git_prefix(argv, rest)
            git_args = rest
        elif gh_args[:2] in (["pr", "create"], ["pr", "merge"]):
            if has_noop_option(source):
                continue
            name = "create" if gh_args[1] == "create" else "merge"
        elif gh_args[:1] == ["api"] and api_merge(shlex.join(["gh", *gh_args])):
            if "--help" not in argv_match.flags(gh_args[1:]):
                name = "merge"
        elif argv and (
            Path(argv[0]).name in {"merge.py", "merge.sh"}
            or (
                len(argv) > 1
                and argv[0] in {"bash", "sh", "python", "python3"}
                and Path(argv[1]).name in {"merge.py", "merge.sh"}
            )
        ):
            name = "merge"
        if not name:
            continue
        raw = source.strip()
        leading = raw.split("git", 1)[0] if name.startswith("git_") and "git" in raw else raw.split("gh", 1)[0]
        if name == "merge" and "merge.py" in raw:
            leading = raw.split("merge.py", 1)[0]
        outer_assignment = bool(
            re.search(
                r"(?:^|[;&|])\s*(?:env\s+)?[A-Za-z_]\w*=\S+\s+(?:bash|sh|zsh)\s+-\w*c",
                command,
            )
        )
        unsafe = bool(re.search(r"(?:^|\s)[A-Za-z_]\w*=", leading)) or not os.path.isdir(where) or outer_assignment
        if unsafe:
            raw = UNBINDABLE + raw
            where = cwd
            selected = cwd
        elif raw.startswith("time git "):
            raw = raw.removeprefix("time ")
        found.append(Operation(name, raw, where, where, prefix, git_args, selected))
    return found


def repository(call: Operation) -> str:
    """Resolve the selected worktree for its policy and config."""
    return git_output(call.git_cwd, *call.prefix, "rev-parse", "--show-toplevel") or call.cwd


def targets_main_call(call: Operation, *, implicit_push: bool = False) -> bool:
    """Guard a protected branch or a push whose target may be protected."""
    if call.name not in {"git_merge", "git_push"}:
        return True
    if call.segment.startswith(UNBINDABLE):
        return True
    if git_output(call.git_cwd, *call.prefix, "branch", "--show-current") in {"main", "master"}:
        return True
    if call.name == "git_push":
        return _push_guarded(call.segment, implicit_push=implicit_push)
    return False


def guarded_operations(command: str, cwd: str, *, implicit_push: bool = False) -> list[Operation]:
    """Keep each guarded action's source, repo and receipt context."""
    return [
        call
        for call in operations(command, cwd)
        if call.name in {"merge", "git_push"} and targets_main_call(call, implicit_push=implicit_push)
    ]


def operation(command: str) -> tuple[str, str, str]:
    """Project the first typed operation for existing callers."""
    found = operations(command)
    return (found[0].name, found[0].segment, found[0].selected_cwd) if found else ("", "", "")


def targets_main(command: str, cwd: str, target: str, name: str, *, implicit_push: bool = False) -> bool:
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
    for raw in _SEP.split(command)[::2]:
        segment = canonical(unwrap(raw))
        if (git := _GIT.match(segment)) and git[2] == "push" and _push_guarded(segment, implicit_push=implicit_push):
            return True
    if re.search(r":(refs/heads/)?(main|master)([\s;&|)]|$)", command):
        return True
    return any(
        subcommand == "push" and any(re.fullmatch(r"\+?(refs/heads/)?(main|master)", token) for token in rest)
        for subcommand, _, rest in argv_match.git_calls(command)
    )


_PUSH_VALUE_OPTS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}


def _push_guarded(segment: str, *, implicit_push: bool = False) -> bool:
    """True when the parsed push can reach main/master, or its destination is not a literal (unbindable: denied)."""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return True
    refs: list[str] = []
    skip = False
    for token in tokens[tokens.index("push") + 1 :]:
        if skip:
            skip = False
        elif token in {"--all", "--mirror"}:
            return True
        elif token in _PUSH_VALUE_OPTS:
            skip = True
        elif not token.startswith("-"):
            refs.append(token)
    if len(refs) < 2:
        return implicit_push  # Config can select main; the receipt binding refuses an implicit refspec.
    for spec in refs[1:]:  # refs[0] is the remote
        dest = spec.lstrip("+").rpartition(":")[2]
        if re.search(r"[$`*?\[\]{}()\\]", dest) or dest.removeprefix("refs/heads/") in {"main", "master"}:
            return True
    return False


_SEP = re.compile(r"(&&|\|\||[;|&\n])")
_WRAPPER = re.compile(r"^(?:[A-Za-z_]\w*=\S*|(?:\S*/)?(?:env|sudo|time|command|exec|nohup))\s+")
_SHELL_C = re.compile(r"\b(?:(?:bash|sh|zsh)\s+-\w*c|eval)\s+([\"'])(.*?)\1")
_API_MERGE = re.compile(r"^gh\s+api\s.*?\b(?:mergePullRequest|enablePullRequestAutoMerge)\b")


def api_merge(segment: str) -> bool:
    """Recognize a merge API endpoint after option values are consumed."""
    if _API_MERGE.match(segment):
        return True
    if not re.match(r"^gh\s+api(?:\s|$)", segment):
        return False
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from scripts.lib.merge_target import parse

    return parse(segment)[0].startswith("https://github.com/")


_PROGRAMS = {"git", "gh", "bash", "sh", "zsh", "python", "python3"}


def unwrap(segment: str) -> str:
    """Strip grouping, env assignments and env/sudo/time/command/exec/nohup prefixes to the command itself."""
    segment = segment.strip().lstrip("({ ").rstrip(")} ")
    while match := _WRAPPER.match(segment):
        segment = segment[match.end() :].lstrip()
    return segment


def canonical(segment: str) -> str:
    """Shell-parse the segment so quoting and an absolute program path (/usr/bin/git) cannot hide it from the matchers.

    An unparsable segment is returned unchanged. ponytail: whitespace tokens only, no variable or alias expansion.
    """
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return segment
    if tokens and "/" in tokens[0] and os.path.basename(tokens[0]) in _PROGRAMS:
        tokens[0] = os.path.basename(tokens[0])
    return shlex.join(tokens) if tokens else segment


def guarded_segments(
    command: str, cwd: str, *, implicit_push: bool = False, _blind: bool = False
) -> list[tuple[str, str, str]]:
    """Project typed guarded operations for existing receipt callers."""
    return [
        (call.name, call.segment, call.cwd) for call in guarded_operations(command, cwd, implicit_push=implicit_push)
    ]


_READ_ONLY = {
    "cd", "pwd", "echo", "printf", "true", "false", ":", "ls", "cat", "head", "tail", "grep", "wc", "sort", "cut",
    "sleep", "test", "[", "date", "whoami",
}  # fmt: skip
_GIT_READ = {
    "status", "log", "diff", "show", "rev-parse", "rev-list", "ls-remote", "ls-files", "describe", "show-ref",
    "cat-file", "shortlog", "blame", "merge-base", "for-each-ref",
}  # fmt: skip
_GH_READ = {("pr", "view"), ("pr", "checks"), ("pr", "status"), ("pr", "list"), ("pr", "diff"), ("auth", "status")}
_GIT_SUB = re.compile(r"^git((?:\s+" + _GIT_OPT + r")*)\s+(\S+)(.*)$")


def read_only(segment: str) -> bool:
    """True for a segment on the allowlist of commands that cannot move a ref, HEAD, the index or the remote config.

    Guarded gh merges and a `git push` to a remote other than `.` count too (they move no local ref, and each guard is
    verified on its own). ponytail: an allowlist, so an unknown command is treated as a mover; a remote that is this
    very repository's path is not recognised.
    """
    plain = re.sub(r"\d*>&\d+|\d*>\s*/dev/null", "", segment)
    if re.search(r"[<>`]|\$\(|--output", plain):
        return False
    try:
        tokens = shlex.split(canonical(plain))
    except ValueError:
        return False
    if not tokens:
        return True
    if tokens[0] in _READ_ONLY:
        return True
    if tokens[0] == "gh":
        return tuple(tokens[1:3]) in _GH_READ | {("pr", "merge")} or api_merge(plain)
    if not (git := _GIT_SUB.match(shlex.join(tokens))):
        return False
    sub, rest = git[2], git[3].split()
    return (
        sub in _GIT_READ
        or (sub == "branch" and rest == ["--show-current"])
        or (sub == "remote" and rest in ([], ["-v"]))
        or (sub == "push" and "." not in rest)
    )


def state_mutated_before_guard(command: str) -> bool:
    """True when a guarded segment follows any segment that is not a known read-only command.

    The receipt binds the sha/ref/remote as they are when the hook runs, so `git branch -f x <sha> && git push origin
    x:main` (or `git push . evil:x`, `git worktree add -B`, `git filter-branch`, a write into .git) would push a
    different sha than the one approved. An allowlist (`read_only`) rather than a list of known movers: such a chain is
    refused; run the steps separately. Scripts, aliases and functions that mutate are seen only as unknown commands.
    """
    mutated = False
    for raw in _flat_segments(re.sub(r"\d*>&\d+", "", command)):  # `2>&1` is not a separator
        segment = canonical(unwrap(raw))
        guard = bool(api_merge(segment) or operation(segment)[0] in {"merge", "git_push"})
        if mutated and guard:
            return True
        mutated = mutated or not read_only(segment)
    return False


def _flat_segments(command: str) -> list[str]:
    """Raw segments in execution order, with `bash -c '...'` / `eval '...'` bodies expanded in place."""
    out: list[str] = []
    position = 0
    for inner in _SHELL_C.finditer(command):
        out += _SEP.split(command[position : inner.start()])[::2] + _flat_segments(inner[2])
        position = inner.end()
    return out + _SEP.split(command[position:])[::2]


def pr_number(segment: str) -> str:
    """Read the explicit PR argument while excluding option tokens."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from scripts.lib.merge_target import parse

    return parse(segment)[0]


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
