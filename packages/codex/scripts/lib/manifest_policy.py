"""Check a diff against a declared manifest and an allow/deny policy; shared by diff_manifest.py, push.py, merge.py.

`check` is pure. `gate` is the one guarded call push.py and merge.py make: it reads the opt-in config keys
`diff_manifest` (off|advisory|enforce, default advisory) and `diff_manifest_policy` (a JSON file), then warns or
refuses. Trace rows are non-authoritative and fail open (Codex ships no trace_row, so the import is optional).
"""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from typing import Any, cast

from . import git_common as git
from .config import config_path, config_value

Changes = list[tuple[str, list[str]]]


def _glob(pattern: str) -> re.Pattern[str]:
    """Compile a path glob: ** crosses directories, * and ? stay inside one segment."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        else:
            c = pattern[i]
            out, i = out + ("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c)), i + 1
    return re.compile(out)


def matches(path: str, globs: list[str]) -> bool:
    """Report whether the path matches any glob."""
    return any(_glob(g).fullmatch(path) for g in globs)


def parse_name_status(text: str) -> Changes:
    """Parse `git diff --name-status -M` output into (status, [paths]); renames carry source then destination."""
    rows: Changes = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            rows.append((parts[0], parts[1:]))
    return rows


def strings(value: object) -> list[str]:
    """Return the string items of a JSON array, else []."""
    return [x for x in cast(list[object], value) if isinstance(x, str)] if isinstance(value, list) else []


def check(
    changes: Changes, policy: dict[str, Any], manifest: list[str] | None = None, linked: bool | None = None
) -> dict[str, Any]:
    """Return {ok, violations[{code, path}]} for name-status changes; every rename path is checked."""
    allow, deny = strings(policy.get("allow")), strings(policy.get("deny"))
    raw = policy.get("docs_sync")
    docs = cast(dict[str, Any], raw) if isinstance(raw, dict) else None
    found: list[dict[str, str]] = []

    def add(code: str, path: str) -> None:
        if {"code": code, "path": path} not in found:
            found.append({"code": code, "path": path})

    for status, paths in changes:
        for path in paths:
            if matches(path, deny):
                add("denied_path", path)
            if (manifest is not None and not matches(path, manifest)) or (allow and not matches(path, allow)):
                add("out_of_manifest", path)
            if docs is not None and (
                matches(path, strings(docs.get("deny"))) or not matches(path, strings(docs.get("allow")) or ["**"])
            ):
                add("docs_sync_deny", path)
        if docs is not None and status.startswith("D"):
            add("docs_sync_deletion", paths[0])
    if policy.get("require_linked_worktree") and linked is False:
        add("not_linked_worktree", "")
    return {"ok": not found, "violations": found}


def linked_worktree() -> bool:
    """True when the current checkout is a linked worktree (git dir differs from the common dir)."""
    return git.output("git", "rev-parse", "--git-dir") != git.output("git", "rev-parse", "--git-common-dir")


def load_json(path: str | Path) -> dict[str, Any] | None:
    """Read a JSON object, or None when unreadable, torn or not an object."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return cast(dict[str, Any], data) if isinstance(data, dict) else None


def trace(label: str, outcome: str, code: str) -> None:
    """Append one non-authoritative row keyed by the label (repo and branch); never raises."""
    try:  # Codex ships no trace_row: the sink is simply absent, and any failure is swallowed
        module = importlib.import_module("hooks.scripts.lib.trace_row")
        module.append_row("diff-manifest", outcome, code, re.sub(r"[^A-Za-z0-9_.@-]", "_", label))
    except Exception:  # fail open: a trace row never decides anything
        return


def diff_changes(head: str, fetch: str = "") -> Changes | None:
    """Return name-status changes for origin/<main>...head, or None when the diff cannot be computed."""
    if fetch and git.run("git", "cat-file", "-e", head).returncode:
        git.run("git", "fetch", "-q", "origin", fetch)
    result = git.run("git", "diff", "--name-status", "-M", f"origin/{git.main()}...{head}")
    return None if result.returncode else parse_name_status(result.stdout)


def gate(pr: str = "") -> None:
    """Opt-in additional check: no policy file or mode off does nothing; advisory warns; enforce raises.

    With a PR number the diff is the PR's own head (fetched if absent); otherwise it is the local HEAD.
    """
    config = config_path()
    mode = (config_value(config, "diff_manifest") if config else "") or "advisory"
    policy_file = config_value(config, "diff_manifest_policy") if config else ""
    if mode == "off" or not policy_file:
        return
    head = git.pr_field(pr, "headRefOid") if pr else "HEAD"
    label = f"{git.repo()}@pr-{pr}" if pr else f"{git.repo()}@{git.branch()}"
    policy, changes = load_json(policy_file), diff_changes(head, f"pull/{pr}/head" if pr else "")
    if policy is None or changes is None:
        found = [{"code": "manifest_unreadable", "path": policy_file}]
    else:
        manifest = strings(policy["manifest"]) if "manifest" in policy else None
        linked = linked_worktree() if policy.get("require_linked_worktree") else None
        found = check(changes, policy, manifest, linked)["violations"]
    if not found:
        trace(label, "ok", "diff_manifest_ok")
        return
    code = found[0]["code"]
    for violation in found:
        trace(label, "refused" if mode == "enforce" else "warned", violation["code"])
        print(f"! diff_manifest {violation['code']}: {violation['path']}")
    if mode == "enforce":
        raise git.WorkflowError(f"diff_manifest:{code}")
