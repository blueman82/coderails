"""Match guarded Git operations and native Claude review invocations."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any, cast

from .destructive_patterns import git_output
from .discipline_common import tool_uses
from .headless_command import headless_cwd_override, headless_prompt

MERGE_SCRIPT = r"""(?:(?:bash|sh|python3?)\s+)?["']?(?:[^\s"']*/)?merge\.(?:py|sh)["']?(?:\s|$)"""
_GIT_OPT = r"(?:-C\s+\S+|-c\s+\S+|--[\w-]+=\S+|--(?:git-dir|work-tree|namespace|exec-path)\s+\S+|--[\w-]+|-[pP])"


def _git_command(segment: str) -> tuple[str, str]:
    """Read a Git subcommand after global options, including quoted -C paths."""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return "", ""
    if tokens[:1] != ["git"]:
        return "", ""
    index, directory = 1, ""
    while index < len(tokens):
        flag = tokens[index]
        if flag in {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}:
            if index + 1 >= len(tokens):
                return "", ""
            if flag == "-C":
                directory = tokens[index + 1]
            index += 2
        elif flag in {"-p", "-P"} or re.fullmatch(r"--[\w-]+(?:=.*)?", flag):
            index += 1
        else:
            break
    return (tokens[index], directory) if index < len(tokens) and tokens[index] in {"merge", "push"} else ("", "")


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
            ("^" + MERGE_SCRIPT, "merge"),
        ):
            if re.search(pattern, segment):
                return name, segment, ""
        if (git_command := _git_command(segment))[0]:
            return f"git_{git_command[0]}", segment, git_command[1]
    return "", "", ""


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
        if _git_command(segment)[0] == "push" and _push_guarded(segment, implicit_push=implicit_push):
            return True
    if re.search(r":(refs/heads/)?(main|master)([\s;&|)]|$)", command):
        return True
    match = re.search(r"\bgit\b[^;&|]*?\bpush\s+(.*)", command)
    return bool(match and re.search(r"(^|\s)\+?(refs/heads/)?(main|master)([\s;&|)]|$)", match[1]))


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


def _shell_parts(command: str) -> list[str]:
    """Split shell operators outside quotes, retaining each original part."""
    masked = list(command)
    quote = ""
    escaped = False
    for index, char in enumerate(command):
        if escaped:
            masked[index] = " "
            escaped = False
        elif char == "\\" and quote != "'":
            masked[index] = " "
            escaped = True
        elif quote:
            masked[index] = " "
            if char == quote:
                quote = ""
        elif char in {"'", '"'}:
            quote = char
            masked[index] = " "
    parts = _SEP.split("".join(masked))
    offset = 0
    original: list[str] = []
    for part in parts:
        original.append(command[offset : offset + len(part)])
        offset += len(part)
    return original


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


def guarded_segments(
    command: str, cwd: str, *, implicit_push: bool = False, _blind: bool = False
) -> list[tuple[str, str, str]]:
    """Every guarded (merge | git_push to main) segment as (operation, segment, effective cwd).

    Track literal cwd changes through groups and shell -c strings. Unknown destinations remain unbindable.
    """
    if prompt := headless_prompt(unwrap(command)):
        return guarded_segments(
            prompt, cwd, implicit_push=implicit_push, _blind=_blind or headless_cwd_override(command)
        )
    found: list[tuple[str, str, str]] = []
    blind = _blind
    stack: list[tuple[str, bool]] = []
    masked = _SHELL_C.sub(lambda match: " " * len(match[0]), command)
    parts = _shell_parts(masked)
    cursor = 0
    for index in range(0, len(parts), 2):
        raw = command[cursor : cursor + len(parts[index])]
        cursor += len(parts[index]) + (len(parts[index + 1]) if index + 1 < len(parts) else 0)
        before, after = parts[index - 1] if index else "", parts[index + 1 : index + 2]
        opened = raw.lstrip()
        while opened.startswith("("):
            stack.append((cwd, blind))
            opened = opened[1:].lstrip()
        closes = len(raw.rstrip()) - len(raw.rstrip().rstrip(")"))
        plain = unwrap(raw)
        for inner in _SHELL_C.finditer(plain):
            found.extend(guarded_segments(inner[2], cwd, implicit_push=implicit_push, _blind=blind))
        if prompt := headless_prompt(plain):
            found.extend(
                guarded_segments(prompt, cwd, implicit_push=implicit_push, _blind=blind or headless_cwd_override(plain))
            )
        plain = _SHELL_C.sub("", plain).strip()
        segment = canonical(plain)
        # An env assignment (GIT_DIR=, GH_REPO=, GIT_CONFIG_*=) can retarget the action: keep the prefix in the
        # segment so action_binding refuses it (binding None -> denied) instead of binding the approved repo.
        stripped = raw.strip().lstrip("({ ")
        tainted = bool(re.search(r"(?:^|\s)[A-Za-z_]\w*=", stripped[: max(stripped.find(plain), 0)]))
        unknown = blind
        if segment.split(None, 1)[:1] == ["cd"]:
            try:
                move = shlex.split(segment)
            except ValueError:
                move = []
            target = os.path.normpath(os.path.join(cwd, os.path.expanduser(move[1]))) if len(move) == 2 else ""
            if before in {"|", "&"} or after[:1] in (["|"], ["&"]):
                continue  # pipeline/background commands run in children; the parent cwd does not move
            if len(move) == 2 and not re.search(r"[$`*?\[]", move[1]) and os.path.isdir(target):
                cwd = target
            else:
                blind = True
        elif api_merge(segment):
            found.append(("merge", UNBINDABLE * unknown + (stripped.rstrip(")} ") if tainted else segment), cwd))
        else:
            name, matched, target_dir = operation(segment)
            if name in {"merge", "git_push"} and targets_main(
                segment, cwd, target_dir, name, implicit_push=implicit_push
            ):
                literal = plain if name == "merge" and plain.startswith("gh pr merge ") else matched
                found.append((name, UNBINDABLE * unknown + (stripped.rstrip(")} ") if tainted else literal), cwd))
        for _ in range(closes):
            if stack:
                cwd, blind = stack.pop()
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
    if prompt := headless_prompt(unwrap(command)):
        return _flat_segments(prompt)
    out: list[str] = []
    position = 0
    for inner in _SHELL_C.finditer(command):
        out += _shell_parts(command[position : inner.start()])[::2] + _flat_segments(inner[2])
        position = inner.end()
    for raw in _shell_parts(command[position:])[::2]:
        prompt = headless_prompt(unwrap(raw))
        out.extend(_flat_segments(prompt) if prompt else [raw])
    return out


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
