#!/usr/bin/env python3
"""The one place that computes (repository, ref, sha) for a guarded action; None means unknowable (callers deny).

git push: needs `git [-C dir] push [opts] <remote> <refspec>`. repository = the remote's PUSH url (host/owner/name),
ref = the DESTINATION full ref (`HEAD` alone means the current branch; a detached HEAD is unknowable), sha = the
rev-parse of the refspec SOURCE. A non-literal refspec ($VAR, globs) and a remote with several push urls are None.
A bare or remote-only push, `-c`/`--git-dir`/`--work-tree`, and env-prefixed commands
are None (push.default, branch.*.remote, pushurl and GIT_* could redirect them).
gh pr merge / gh api .../merge: ref = the PR base, sha = the live PR headRefOid, repository = origin, -R, the PR URL or
the api path. The command must pin that sha (`--match-head-commit <sha>` / `sha=<sha>`). The merge.py helper must
name the same literal sha with `--expected-head <sha>` before a receipt can bind. Option values are skipped when
finding the PR argument. merge-async is guarded but unbindable because it may merge a stack. Used by the hook,
the receipt CLI and merge.py's direct receipt check.
Refuses (None) --all/--mirror/--tags/--delete, several refspecs, deletes, and remotes that are not host/owner/name.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from typing import Any

_SCHEME_URL = re.compile(
    r"^[a-z][a-z0-9+.-]*://(?:[^@/\s]+@)?([^:/\s]+)(?::[0-9]+)?/([^/\s]+/[^/?#\s]+?)(?:\.git)?/?$", re.I
)
_SCP_URL = re.compile(r"^(?:[^@/\s]+@)?([^:/\s]+):([^/\s]+/[^/?#\s]+?)(?:\.git)?/?$", re.I)
_BARE_URL = re.compile(r"^([^:/\s]+)/([^/\s]+/[^/?#\s]+?)(?:\.git)?/?$", re.I)
_PR_URL = re.compile(r"^https://([^/\s]+)/([^/\s]+/[^/\s]+)/pull/(\d+)/?$")
_SCRIPT = re.compile(r"(?:^|/)merge\.py$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_NON_LITERAL = re.compile(r"[$`*?\[\]{}()\\]")
_VALUE_OPTS = {"-o", "--push-option"}
_REFUSED = {"--all", "--mirror", "--tags", "--delete", "-d", "--prune"}
_MERGE_VALUE_OPTS = {"-R", "--repo", "-b", "--body", "-F", "--body-file", "-t", "--subject", "-A", "--author-email"}


def git_out(cwd: str, *args: str) -> str:
    """Stdout of a git command, "" on any failure."""
    try:
        done = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def normalise_repository(url: str) -> str | None:
    """host/owner/name in lower case from an https, ssh or scp-style URL; None for anything else."""
    value = url.strip()
    match = next((match for pattern in (_SCHEME_URL, _SCP_URL, _BARE_URL) if (match := pattern.match(value))), None)
    return f"{match[1]}/{match[2]}".lower() if match and not {".", ".."} & set(match[2].split("/")) else None


def pr_view(number: str, cwd: str, repo: str | None = None) -> tuple[str, str] | None:
    """(base branch, head sha) of a PR from the live `gh pr view`; None on any failure."""
    cmd = ["gh", "pr", "view", number, "--json", "baseRefName,headRefOid"] + (["-R", repo] if repo else [])
    try:
        done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=4, check=False)
        if done.returncode:
            return None
        data: Any = json.loads(done.stdout)
        return str(data["baseRefName"]), str(data["headRefOid"])
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return None


def pr_number_for_branch(branch: str, cwd: str) -> str | None:
    """Resolve the first PR for a branch as merge.py does; refuse an empty or failed lookup."""
    if not branch:
        return None
    try:
        done = subprocess.run(
            ["gh", "pr", "list", "--head", branch, "--json", "number"], cwd=cwd,
            capture_output=True, text=True, timeout=4, check=False,
        )  # fmt: skip
        if done.returncode:
            return None
        rows: Any = json.loads(done.stdout)
        number = rows[0]["number"]
        return str(number) if isinstance(number, int) and number > 0 else None
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError):
        return None


def _full_ref(name: str) -> str:
    return name if name.startswith("refs/") else f"refs/heads/{name}"


def _push(tokens: list[str], cwd: str) -> dict[str, str] | None:
    at = tokens.index("push")
    head = tokens[:at]
    if head[:1] != ["git"] or (len(head) != 1 and not (len(head) == 3 and head[1] == "-C")):
        return None  # env prefix, -c, --git-dir, --work-tree ... can retarget the push
    if len(head) == 3:
        cwd = os.path.normpath(os.path.join(cwd, head[2]))
    positional: list[str] = []
    skip = False
    for token in tokens[at + 1 :]:
        if skip:
            skip = False
        elif token.partition("=")[0] in _REFUSED | {"--repo", "--receive-pack", "--exec"}:
            return None
        elif token in _VALUE_OPTS:
            skip = True
        elif not token.startswith("-"):
            positional.append(token)
    if len(positional) != 2:
        return None  # bare / remote-only pushes follow push.default and branch.*.remote: unknowable here
    remote, refspec = positional[0], positional[1].lstrip("+")
    source, colon, dest = refspec.partition(":")
    if not colon and source == "HEAD":
        dest = git_out(cwd, "branch", "--show-current")  # empty on a detached HEAD
    elif not colon:
        dest = source
    if not source or not dest or _NON_LITERAL.search(refspec):
        return None  # $VAR, $(...), globs: the shell decides the real ref
    urls = git_out(cwd, "remote", "get-url", "--push", "--all", remote).splitlines() or [remote]
    repository = normalise_repository(urls[0]) if len(urls) == 1 else None  # several pushurls: all are pushed to
    sha = git_out(cwd, "rev-parse", "--verify", "--quiet", f"{source}^{{commit}}")
    return {"repository": repository, "ref": _full_ref(dest), "sha": sha} if repository and sha else None


def _pr_target(tokens: list[str], segment: str, cwd: str) -> tuple[str, str | None, str | None] | None:
    """(PR number, repo spec or None, pinned sha or None) for gh pr merge | gh api .../merge | merge script."""
    api = re.search(r"repos/([^/\s]+/[^/\s]+)/pulls/(\d+)/merge(?=\s|$)", segment)
    if api and tokens[:2] == ["gh", "api"]:
        pin = next((t[4:] for t in tokens if t.startswith("sha=")), None)
        return api[2], api[1], pin
    script = next((i for i, token in enumerate(tokens[:2]) if _SCRIPT.search(token)), None)
    if script is not None:
        if script == 1 and os.path.basename(tokens[0]) not in {"python", "python3"}:
            return None
        args = tokens[script + 1 :]
        if len(args) == 3 and args[1] == "--expected-head":
            arg, pin = args[0], args[2]
        elif len(args) == 2 and args[1].startswith("--expected-head="):
            arg, pin = args[0], args[1].split("=", 1)[1]
        else:
            return None
        if not _SHA.fullmatch(pin):
            return None
        if arg == "auto":
            branch = git_out(cwd, "branch", "--show-current")
            default = git_out(cwd, "symbolic-ref", "refs/remotes/origin/HEAD").rsplit("/", 1)[-1] or "main"
            if branch == default:
                return None
            arg = pr_number_for_branch(branch, cwd) or ""
        elif not arg.isdigit():
            arg = pr_number_for_branch(arg, cwd) or ""
        return (arg, None, pin) if arg.isdigit() else None
    if tokens[:3] != ["gh", "pr", "merge"]:
        return None
    args, i = tokens[3:], 0
    positional: list[str] = []
    repo = pin = None
    while i < len(args):
        name, eq, value = args[i].partition("=")
        if re.match(r"^-[A-Za-z]{2,}", args[i]) and re.search(r"[RbFtA]", args[i][1:]):
            return None  # combined short flags hide a value option
        if name in _MERGE_VALUE_OPTS | {"--match-head-commit"}:
            if not eq:
                i += 1
                if i >= len(args):
                    return None
                value = args[i]
            if name in {"-R", "--repo"}:
                repo = value
            elif name == "--match-head-commit":
                pin = value
        elif not name.startswith("-"):
            positional.append(args[i])
        i += 1
    if len(positional) != 1:
        return None
    if url := _PR_URL.match(positional[0]):
        spec = f"{url[1]}/{url[2]}"
        return (url[3], spec, pin) if repo in {None, spec, url[2]} else None
    return (positional[0], repo, pin) if positional[0].isdigit() else None


def _merge(tokens: list[str], segment: str, cwd: str) -> dict[str, str] | None:
    target = _pr_target(tokens, segment, cwd)
    if target is None:
        return None
    number, repo, pin = target
    view = pr_view(number, cwd, repo)
    if view is None or not _SHA.match(view[1]) or pin != view[1]:
        return None  # unknown PR, or the command does not pin the live head sha
    where = repo or git_out(cwd, "remote", "get-url", "origin")
    repository = normalise_repository(f"github.com/{where}" if repo and repo.count("/") == 1 else where)
    return {"repository": repository, "ref": _full_ref(view[0]), "sha": view[1]} if repository else None


def merge_number(segment: str, cwd: str) -> str:
    """Resolve the PR number named by a merge command, including merge.py branch and auto targets."""
    try:
        target = _pr_target(shlex.split(segment), segment, cwd)
    except ValueError:
        return ""
    return target[0] if target else ""


def binding(kind: str, segment: str, cwd: str) -> dict[str, str] | None:
    """{repository, ref, sha} for one guarded segment (kind merge | git_push), or None when unknowable."""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return None
    if tokens and re.match(r"^[A-Za-z_]\w*=", tokens[0]):
        return None  # an env assignment prefix (also the matcher's UNBINDABLE marker) can retarget the action
    if kind == "git_push" and "push" in tokens:
        return _push(tokens, cwd)
    if kind == "merge":
        return _merge(tokens, segment, cwd)
    return None
