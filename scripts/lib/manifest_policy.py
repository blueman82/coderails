"""Check a diff against a declared manifest and an allow/deny policy; shared by diff_manifest.py, push.py, merge.py.

`check` is pure. `violations` is the one policy evaluation every publication path shares: it reads the typed config
keys `diff_manifest` (off|advisory|enforce, default enforce) and `diff_manifest_policy` (a JSON file; null means the
shipped policy/diff-policy.default.json), then returns the refusals. `gate` raises on them (push.py), and
publication_gate registers `violations` for merge.py and the direct-merge hooks. Trace rows are non-authoritative and
fail open: a failure to write one never decides anything.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, cast

from . import git_common as git
from .config import config_path
from .config_strict import ConfigRejected, strict_settings

DEFAULT_POLICY = Path(__file__).resolve().parents[2] / "policy" / "diff-policy.default.json"
MODES = ("off", "advisory", "enforce")
PROTECTED_POLICY_PATHS = [
    ".coderails/workflow.config.yaml",
    "policy/diff-policy*.json",
    "packages/codex/policy/diff-policy*.json",
]
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
        status, old_mode, new_mode = meta[4], meta[0][1:], meta[1]
        count = 2 if status[0] in "RC" else 1
        paths = tokens[i + 1 : i + 1 + count]
        if new_mode in ("120000", "160000") and not status.startswith("D"):
            status += ":" + new_mode
        elif status[0] in "MRC" and old_mode != new_mode and "000000" not in (old_mode, new_mode):
            status += ":mode"  # a chmod (100644 <-> 100755) rides in a change that may look like a plain edit
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
    """Return {ok, violations[{code, path}]} for parsed changes; every rename path is checked."""
    allow, deny = strings(policy.get("allow")), strings(policy.get("deny"))
    raw = policy.get("docs_sync")
    docs = cast(dict[str, Any], raw) if isinstance(raw, dict) else None
    statuses, limit = strings(policy.get("statuses")), policy.get("max_paths")
    found: list[dict[str, str]] = []

    def add(code: str, path: str) -> None:
        if {"code": code, "path": path} not in found:
            found.append({"code": code, "path": path})

    if isinstance(limit, int) and not isinstance(limit, bool) and len(changes) > limit:
        add("too_many_paths", changes[limit][1][-1])
    for status, paths in changes:
        if statuses and status[0] not in statuses:
            add("status_not_allowed", paths[-1])
        for path in paths:
            if matches(path, deny) and (not status.startswith("D") or matches(path, PROTECTED_POLICY_PATHS)):
                add("denied_path", path)
            if (manifest is not None and not matches(path, manifest)) or (allow and not matches(path, allow)):
                add("out_of_manifest", path)
            if docs is not None and (
                matches(path, strings(docs.get("deny"))) or not matches(path, strings(docs.get("allow")) or ["**"])
            ):
                add("docs_sync_deny", path)
        if status.startswith("T") or status.endswith((":120000", ":160000")):
            add("special_file_type", paths[-1])
        if status.endswith(":mode"):
            add("mode_change", paths[-1])
        if docs is not None and status.startswith("D"):
            add("docs_sync_deletion", paths[0])
    if policy.get("require_linked_worktree") and linked is False:
        add("not_linked_worktree", "")
    return {"ok": not found, "violations": found}


def linked_worktree() -> bool:
    """True when the current checkout is a linked worktree (git dir differs from the common dir)."""
    return git.output("git", "rev-parse", "--git-dir", check=True) != git.output(
        "git", "rev-parse", "--git-common-dir", check=True
    )


def load_json(path: str | Path) -> dict[str, Any] | None:
    """Read a JSON object, or None when unreadable, torn or not an object."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return cast(dict[str, Any], data) if isinstance(data, dict) else None


def trace(label: str, outcome: str, code: str, command: str = "diff-manifest") -> None:
    """Append one non-authoritative row keyed by the label (repo and branch); never raises."""
    try:  # both packages ship hooks/scripts/lib/trace_row.py; any failure to import or write is swallowed
        module = importlib.import_module("hooks.scripts.lib.trace_row")
        module.append_row(command, outcome, code, re.sub(r"[^A-Za-z0-9_.@-]", "_", label))
    except Exception:  # fail open: a trace row never decides anything
        return


def diff_changes(head: str, fetch: str = "", base: str = "") -> Changes | None:
    """Return parsed raw -z changes for the PR base SHA (or local main) to head."""
    if fetch and git.run("git", "cat-file", "-e", head).returncode:
        git.run("git", "fetch", "-q", "origin", fetch)
    if not head:
        return None  # an unresolved PR head must never fall back to diffing the local HEAD
    if base:
        if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", base):
            return None
        if git.run("git", "cat-file", "-e", base).returncode:
            git.run("git", "fetch", "-q", "origin", base)
        if git.run("git", "cat-file", "-e", base).returncode:
            return None
    result = git.run("git", "diff", "--raw", "-z", "-M", f"{base or f'origin/{git.main()}'}...{head}")
    return None if result.returncode else parse_raw_z(result.stdout)


def publication_session() -> str:
    """Session identity supplied by the active provider or publication hook."""
    session = os.environ.get("CODERAILS_PUBLICATION_SESSION_ID")
    if session is None:
        session = (
            os.environ.get("CLAUDE_CODE_SESSION_ID")
            or os.environ.get("CODEX_SESSION_ID")
            or os.environ.get("CODEX_THREAD_ID")
            or ""
        )
    if not session or session != session.strip() or "/" in session or ".." in session:
        return ""
    return session


def _graph_path(session: str) -> Path | None:
    """Return the current repository's supported graph-state path."""
    plugin = Path(__file__).resolve().parents[2]
    root_key = (
        "CODERAILS_AGENTIC_LOOP_DIR" if (plugin / ".codex-plugin/plugin.json").is_file() else "CLAUDE_AGENTIC_LOOP_DIR"
    )
    root = Path(os.environ.get(root_key) or Path.home() / ".coderails/agentic-loop")
    common = git.output("git", "rev-parse", "--path-format=absolute", "--git-common-dir")
    current = git.output("git", "rev-parse", "--show-toplevel")
    return root / common.replace("/", "-") / session / "progress.json" if common and current and session else None


def unit_manifest(progress: str, unit: str) -> list[str]:
    """Read a unit manifest from this repository's supported, session-owned graph state."""
    state = load_json(progress)
    units = (state or {}).get("work_units")
    if state is None or not isinstance(units, dict):
        raise ValueError("progress unreadable")
    if any(not isinstance(state.get(key), str) or not str(state[key]).strip() for key in ("session_id", "loop_id")):
        raise ValueError("progress ownership missing")
    owner = str(state["session_id"]).replace("/", "_").replace("..", "")
    expected = _graph_path(owner)
    session = publication_session()
    if not session:
        raise ValueError("publication session missing")
    if not expected or not Path(progress).is_absolute() or Path(progress).resolve() != expected.resolve():
        raise ValueError("progress repository mismatch")
    if session != owner:
        raise ValueError("progress session mismatch")
    entry = cast(dict[str, Any], units).get(unit)
    if not isinstance(entry, dict):
        raise ValueError("unit missing")
    manifest = cast(dict[str, Any], entry).get("manifest")
    if not isinstance(manifest, list) or not all(isinstance(path, str) for path in cast(list[object], manifest)):
        raise ValueError("unit manifest invalid")
    return strings(cast(list[object], manifest))


def active_graph_unit() -> bool:
    """True when the current repository has graph units for this session."""
    session = publication_session()
    if not session:
        return False
    path = _graph_path(session)
    if not path:
        return False
    if not path.is_file():
        root = path.parents[2]
        try:
            candidates = sorted(
                directory / session / "progress.json" for directory in root.iterdir() if directory.is_dir()
            )
        except OSError:
            return False
        existing = [candidate for candidate in candidates if candidate.is_file()]
        if len(existing) > 1:
            return True  # multiple same-session fallbacks cannot identify this repository's graph
        if not existing:
            return False
        path = existing[0]
    state = load_json(path)
    if state is None or state.get("session_id") != session or not isinstance(state.get("work_units"), dict):
        return True
    return bool(state["work_units"])


def unit_flags(arguments: list[str]) -> tuple[list[str], str, str]:
    """Split `--unit N --progress PATH` out of an argument list: (remaining arguments, unit, progress)."""
    rest: list[str] = []
    flags = {"--unit": "", "--progress": ""}
    seen: set[str] = set()
    items = iter(arguments)
    for argument in items:
        flag, equals, value = argument.partition("=")
        if flag in flags:
            value = value if equals else next(items, "")
            if flag in seen or not value or value.startswith("--"):
                raise git.WorkflowError(f"diff_manifest:manifest_unreadable: invalid {flag} value")
            flags[flag] = value
            seen.add(flag)
        else:
            rest.append(argument)
    return rest, flags["--unit"], flags["--progress"]


def settings() -> tuple[str, str, bool]:
    """(mode, policy file, mode_invalid) from the typed config; no config file means the defaults."""
    path = config_path()
    values = strict_settings(path) if path else {}
    mode = str(values.get("diff_manifest", "enforce"))
    configured_policy = values.get("diff_manifest_policy")
    policy = str(DEFAULT_POLICY if configured_policy is None else configured_policy)
    return (mode if mode in MODES else "enforce"), policy, mode not in MODES


def _evaluate(pr: str, head: str, policy_file: str, unit: str, progress: str, label: str) -> list[dict[str, str]]:
    """Check the diff against the policy; unusable inputs yield one manifest_unreadable violation."""
    policy = load_json(policy_file)
    default = load_json(DEFAULT_POLICY)
    base = git.pr_field(pr, "baseRefOid") if pr else ""
    changes = (
        diff_changes(head or (git.pr_field(pr, "headRefOid") if pr else "HEAD"), f"pull/{pr}/head" if pr else "", base)
        if not pr or base
        else None
    )
    if policy is None or default is None or changes is None or not isinstance(policy.get("manifest", []), list):
        return [{"code": "manifest_unreadable", "path": policy_file}]
    policy["deny"] = strings(default.get("deny")) + strings(policy.get("deny"))
    manifest = strings(policy["manifest"]) if "manifest" in policy else None
    if bool(unit) != bool(progress):  # a lone flag would otherwise be silently ignored
        return [{"code": "manifest_unreadable", "path": "--unit and --progress must be given together"}]
    scoped = None
    if unit:
        try:
            scoped = unit_manifest(progress, unit)
        except ValueError:
            return [{"code": "manifest_unreadable", "path": progress}]
    if manifest is None:
        trace(label, "legacy", "manifest_legacy_absent")
    linked = linked_worktree() if policy.get("require_linked_worktree") else None
    found = cast(list[dict[str, str]], check(changes, policy, manifest, linked)["violations"])
    if scoped is not None:
        found += [v for v in check(changes, {}, scoped)["violations"] if v not in found]
    if not unit and not progress and active_graph_unit():
        found.append({"code": "manifest_unreadable", "path": "graph unit requires --unit and --progress"})
    return found


def violations(pr: str = "", unit: str = "", progress: str = "", head: str = "") -> list[dict[str, str]]:
    """Refusals as {code: "diff_manifest:<code>", detail}; off and advisory return none (advisory warns and traces).

    With a PR number the diff is the PR's own head (fetched if absent); otherwise it is the local HEAD. An internal
    error refuses with manifest_internal_error under enforce and fails open under advisory.
    """
    try:
        mode, policy_file, invalid = settings()
    except ConfigRejected as error:
        trace(f"pr-{pr}" if pr else "config", "refused", "config_rejected")
        print(f"! {error}", file=sys.stderr)
        return [{"code": "config_rejected", "detail": str(error)}]
    except Exception:  # noqa: BLE001 - unreadable config must not turn the default-ON gate off or raise raw
        trace(f"pr-{pr}" if pr else "config", "refused", "manifest_internal_error")
        print("! diff_manifest manifest_internal_error: config unreadable", file=sys.stderr)
        return [{"code": "diff_manifest:manifest_internal_error", "detail": "config unreadable"}]
    if mode == "off":
        return []
    label = f"pr-{pr}" if pr else "local"
    try:
        label = f"{git.repo()}@pr-{pr}" if pr else f"{git.repo()}@{git.branch()}"
        found = _evaluate(pr, head, policy_file, unit, progress, label)
    except Exception:  # noqa: BLE001 - metadata and diff errors share the manifest mode
        found = [{"code": "manifest_internal_error", "path": "internal error"}]
    if invalid:
        trace(label, "warned", "diff_manifest_mode_invalid")
        print("! diff_manifest diff_manifest_mode_invalid: treated as enforce", file=sys.stderr)
    if not found:
        trace(label, "ok", "diff_manifest_ok")
        return []
    unusable = found[0]["code"].startswith("manifest_")
    outcome = "refused" if mode == "enforce" else "failed_open" if unusable else "warned"
    for violation in found:
        trace(label, outcome, violation["code"])
        # stderr, because stdout is a hook's JSON reply
        print(f"! diff_manifest {violation['code']}: {violation['path']}", file=sys.stderr)
    if mode != "enforce":
        return []
    return [{"code": f"diff_manifest:{v['code']}", "detail": v["path"]} for v in found]


def gate(pr: str = "", unit: str = "", progress: str = "") -> None:
    """Raise WorkflowError("diff_manifest:<code>") for the first refusal; push.py calls this before pushing."""
    if not publication_session():
        trace("publication", "refused", "session_missing", command="publication")
        raise git.WorkflowError("publication:session_missing")
    found = violations(pr, unit, progress)
    if found:
        raise git.WorkflowError(found[0]["code"])
