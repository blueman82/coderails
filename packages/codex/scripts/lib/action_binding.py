#!/usr/bin/env python3
"""The one place that computes (repository, ref, sha) for a guarded action; None means unknowable (callers deny).

git push: repository = the named remote's normalised host/owner/name, ref = the DESTINATION full ref, sha = the
rev-parse of the refspec SOURCE (`git push origin feature:main` pushes feature, never HEAD).
gh pr merge / gh api .../merge: ref = the PR base, sha = the live PR headRefOid, repository = origin (or -R).
Used by the hook, the receipt CLI and merge.py. Refuses (None) --all/--mirror/--tags/--delete, several refspecs,
deletes, a detached HEAD with no refspec, and remotes that are not host/owner/name.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from typing import Any

_URL = re.compile(r"^(?:[a-z][a-z0-9+.-]*://)?(?:[^@/\s]+@)?([^:/\s]+)[:/]([^/\s]+/[^\s]+?)(?:\.git)?/?$", re.I)
_VALUE_OPTS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
_REFUSED = {"--all", "--mirror", "--tags", "--delete", "-d", "--prune"}


def git_out(cwd: str, *args: str) -> str:
    """Stdout of a git command, "" on any failure."""
    try:
        done = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def normalise_repository(url: str) -> str | None:
    """host/owner/name in lower case from an https, ssh or scp-style URL; None for anything else."""
    match = _URL.match(url.strip())
    return f"{match[1]}/{match[2]}".lower() if match else None


def pr_view(number: str, cwd: str, repo: str | None = None) -> tuple[str, str] | None:
    """(base branch, head sha) of a PR from the live `gh pr view`; None on any failure."""
    cmd = ["gh", "pr", "view", number, "--json", "baseRefName,headRefOid"] + (["-R", repo] if repo else [])
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=4, check=False).stdout
        data: Any = json.loads(out)
        return str(data["baseRefName"]), str(data["headRefOid"])
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return None


def _full_ref(name: str) -> str:
    return name if name.startswith("refs/") else f"refs/heads/{name}"


def _push(tokens: list[str], cwd: str) -> dict[str, str] | None:
    if "-C" in tokens[: tokens.index("push")]:
        at = tokens.index("-C")
        cwd = os.path.normpath(os.path.join(cwd, tokens[at + 1])) if at + 1 < len(tokens) else cwd
    rest = tokens[tokens.index("push") + 1 :]
    positional: list[str] = []
    skip = False
    for token in rest:
        if skip:
            skip = False
        elif token in _REFUSED:
            return None
        elif token in _VALUE_OPTS:
            skip = True
        elif not token.startswith("-"):
            positional.append(token)
    if len(positional) > 2:
        return None
    remote = positional[0] if positional else "origin"
    branch = git_out(cwd, "branch", "--show-current")
    refspec = positional[1].lstrip("+") if len(positional) == 2 else branch
    source, _, dest = refspec.partition(":")
    dest = dest if ":" in refspec else source
    if not source or not dest:
        return None
    repository = normalise_repository(git_out(cwd, "remote", "get-url", remote) or remote)
    sha = git_out(cwd, "rev-parse", "--verify", "--quiet", f"{source}^{{commit}}")
    return {"repository": repository, "ref": _full_ref(dest), "sha": sha} if repository and sha else None


def _merge(tokens: list[str], segment: str, cwd: str) -> dict[str, str] | None:
    repo = next((tokens[i + 1] for i, t in enumerate(tokens[:-1]) if t in {"-R", "--repo"}), None)
    api = re.search(r"/pulls/(\d+)/merge", segment)
    number = api[1] if api else next((m[1] for t in tokens[3:] if (m := re.search(r"(?:^|/pull/)(\d+)$", t))), "")
    view = pr_view(number, cwd, repo) if number else None
    if view is None:
        return None
    where = repo or git_out(cwd, "remote", "get-url", "origin")
    repository = normalise_repository(f"github.com/{where}" if repo and repo.count("/") == 1 else where)
    return {"repository": repository, "ref": _full_ref(view[0]), "sha": view[1]} if repository and view[1] else None


def binding(kind: str, segment: str, cwd: str) -> dict[str, str] | None:
    """{repository, ref, sha} for one guarded segment (kind merge | git_push), or None when unknowable."""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return None
    if kind == "git_push" and "push" in tokens:
        return _push(tokens, cwd)
    if kind == "merge":
        return _merge(tokens, segment, cwd)
    return None
