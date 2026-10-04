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
    return re.compile(out, re.IGNORECASE)  # case-insensitive checkouts: Docs/x is docs/x


def matches(path: str, globs: list[str]) -> bool:
    """Report whether the path matches any glob."""
    return any(_glob(g).fullmatch(path) for g in globs)


def _unquote(path: str) -> str:
    """Undo git C-quoting of a path so globs see the real characters."""
    if len(path) < 2 or not (path.startswith('"') and path.endswith('"')):
        return path
    body = path[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
    return body.encode("latin-1", "replace").decode("utf-8", "replace")


def parse_raw_z(text: str) -> Changes:
    """Parse `git diff --raw -z -M` into (status, [paths]); a symlink or gitlink destination adds a :mode suffix."""
    tokens, i = text.split("\0"), 0
    rows: Changes = []
    while i < len(tokens) and tokens[i].startswith(":"):
        meta = tokens[i].split()
        status, new_mode = meta[4], meta[1]
        count = 2 if status[0] in "RC" else 1
        paths = tokens[i + 1 : i + 1 + count]
        if new_mode in ("120000", "160000") and not status.startswith("D"):
            status += ":" + new_mode
        rows.append((status, paths))
        i += 1 + count
    return rows


def parse_name_status(text: str) -> Changes:
    """Parse `git diff --name-status -M` output into (status, [paths]); renames carry source then destination."""
    rows: Changes = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            rows.append((parts[0], [_unquote(x) for x in parts[1:]]))
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
        if status.startswith("T") or status.endswith((":120000", ":160000")):
            add("special_file_type", paths[-1])
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
    if not head:
        return None  # an unresolved PR head must never fall back to diffing the local HEAD
    result = git.run("git", "diff", "--raw", "-z", "-M", f"origin/{git.main()}...{head}")
    return None if result.returncode else parse_raw_z(result.stdout)


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
    try:  # advisory must never abort push or merge on an unexpected error
        policy, changes = load_json(policy_file), diff_changes(head, f"pull/{pr}/head" if pr else "")
        found: list[dict[str, str]] = []
        if policy is None or changes is None or not isinstance(policy.get("manifest", []), list):
            unreadable = True
            found = [{"code": "manifest_unreadable", "path": policy_file}]
        else:
            unreadable = False
            manifest = strings(policy["manifest"]) if "manifest" in policy else None
            if manifest is None:
                trace(label, "legacy", "manifest_legacy_absent")
            linked = linked_worktree() if policy.get("require_linked_worktree") else None
            found = check(changes, policy, manifest, linked)["violations"]
    except Exception:  # fail open: a bug here is not a policy verdict
        trace(label, "failed_open", "manifest_unreadable")
        print("! diff_manifest manifest_unreadable: internal error")
        return
    if not found:
        trace(label, "ok", "diff_manifest_ok")
        return
    code = found[0]["code"]
    for violation in found:
        outcome = "refused" if mode == "enforce" else "failed_open" if unreadable else "warned"
        trace(label, outcome, violation["code"])
        print(f"! diff_manifest {violation['code']}: {violation['path']}")
    if mode == "enforce":
        raise git.WorkflowError(f"diff_manifest:{code}")
