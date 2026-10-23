"""Vendored subset of hooks/scripts/lib/pr_workflow_match.py (operation, targets_main, guarded_segments).

Parity-tested against the Claude copy in packages/tests/test_codex_action_authority.py: change both together.
"""

from __future__ import annotations

import os
import re
import shlex
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
    for raw in _SEP.split(command)[::2]:
        segment = canonical(unwrap(raw))
        if (git := _GIT.match(segment)) and git[2] == "push":
            return _push_guarded(segment)
    if re.search(r":(refs/heads/)?(main|master)([\s;&|)]|$)", command):
        return True
    match = re.search(r"\bgit\b[^;&|]*?\bpush\s+(.*)", command)
    return bool(match and re.search(r"(^|\s)\+?(refs/heads/)?(main|master)([\s;&|)]|$)", match[1]))


_PUSH_VALUE_OPTS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}


def _push_guarded(segment: str) -> bool:
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
    for spec in refs[1:]:  # refs[0] is the remote
        dest = spec.lstrip("+").rpartition(":")[2]
        if re.search(r"[$`*?\[\]{}()\\]", dest) or dest.removeprefix("refs/heads/") in {"main", "master"}:
            return True
    return False


_SEP = re.compile(r"(&&|\|\||[;|&\n])")
_WRAPPER = re.compile(r"^(?:[A-Za-z_]\w*=\S*|(?:\S*/)?(?:env|sudo|time|command|exec|nohup))\s+")
_SHELL_C = re.compile(r"\b(?:(?:bash|sh|zsh)\s+-\w*c|eval)\s+([\"'])(.*?)\1")
_API_MERGE = re.compile(r"^gh\s+api\s+\S*/pulls/\d+/merge(?:\s|$)")
_PROGRAMS = {"git", "gh", "bash", "sh", "zsh", "python", "python3"}
UNBINDABLE = "CODERAILS_UNBINDABLE=1 "  # an env-style prefix: action_binding refuses it, so the segment is denied


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


def guarded_segments(command: str, cwd: str) -> list[tuple[str, str, str]]:
    """Every guarded (merge | git_push to main) segment as (operation, segment, effective cwd).

    A plain `cd <dir>` (shell-parsed, an existing directory) moves the effective cwd for the segments after it, so the
    receipt hash binds the directory the operation really runs in. A cd that cannot be followed (variable, `cd -`, a
    missing directory, a subshell group) makes every later guard unbindable, as does a cd before `bash -c`/`eval`.
    Quoting and absolute program paths are normalised (`canonical`); wrappers are unwrapped (env/sudo/time prefixes,
    subshell and brace groups, `bash -c '...'`, `eval '...'`, `gh api .../merge`).
    Still unmatched: xargs, aliases, functions, scripts that push, `gh api` ref/contents writes, other branches.
    ponytail: tokens only, no variable or alias expansion (a non-literal destination is guarded and unbindable).
    """
    found: list[tuple[str, str, str]] = []
    blind = False  # the real cwd is unknown from here on
    group_blind = False  # inside a `( cd x && ... )` group
    parts = _SEP.split(_SHELL_C.sub(" ", command))
    for index in range(0, len(parts), 2):
        raw, before, after = parts[index], parts[index - 1] if index else "", parts[index + 1 : index + 2]
        plain = unwrap(raw)
        segment = canonical(plain)
        # An env assignment (GIT_DIR=, GH_REPO=, GIT_CONFIG_*=) can retarget the action: keep the prefix in the
        # segment so action_binding refuses it (binding None -> denied) instead of binding the approved repo.
        stripped = raw.strip().lstrip("({ ")
        tainted = bool(re.search(r"(?:^|\s)[A-Za-z_]\w*=", stripped[: max(stripped.find(plain), 0)]))
        unknown = blind or group_blind
        if segment.split(None, 1)[:1] == ["cd"]:
            try:
                move = shlex.split(segment)
            except ValueError:
                move = []
            target = os.path.normpath(os.path.join(cwd, os.path.expanduser(move[1]))) if len(move) == 2 else ""
            grouped = raw.lstrip().startswith("(")
            if not grouped and (before in {"|", "&"} or after[:1] in (["|"], ["&"])):
                continue  # pipeline/background commands run in children; the parent cwd does not move
            if len(move) == 2 and not re.search(r"[$`*?\[]", move[1]) and os.path.isdir(target) and not grouped:
                cwd = target
            elif grouped:
                group_blind = True
            else:
                blind = True
        elif _API_MERGE.match(segment):
            found.append(("merge", UNBINDABLE * unknown + (stripped.rstrip(")} ") if tainted else segment), cwd))
        else:
            name, matched, target_dir = operation(segment)
            if name in {"merge", "git_push"} and targets_main(segment, cwd, target_dir, name):
                found.append((name, UNBINDABLE * unknown + (stripped.rstrip(")} ") if tainted else matched), cwd))
        if raw.rstrip().endswith(")"):
            group_blind = False
    after_cd = bool(re.search(r"\bcd\b", _SHELL_C.sub(" ", command)))
    for inner in _SHELL_C.finditer(command):
        found.extend(  # a cd outside the string: its effect on the inner command's cwd is not followed
            (name, UNBINDABLE * after_cd + seg, where) for name, seg, where in guarded_segments(inner[2], cwd)
        )
    return found


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
        return tuple(tokens[1:3]) in _GH_READ | {("pr", "merge")} or bool(_API_MERGE.match(plain))
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
        guard = bool(_API_MERGE.match(segment) or operation(segment)[0] in {"merge", "git_push"})
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
