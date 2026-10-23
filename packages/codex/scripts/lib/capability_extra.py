"""Extensions installed into scripts/capability.py: `worktree` argument, more repo.inspect ops, and cmd.run.

`install(cap, tools)` is the only entry point (capability.py stays small). Everything here goes through the
capability module's own safe_path / REF / check / run / sandboxed, so the refusal codes are the same.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import itertools
import json
import os
import subprocess
import tempfile
from collections.abc import Generator
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, cast

Result = tuple[int, dict[str, Any], list[dict[str, str]]]  # same shape as capability.Result
Tool = Callable[[object], Result]
OPS = ("show", "blame", "wc", "sha256", "glob")
SPECS: dict[str, dict[str, tuple[type, Any]]] = {
    "show": {"spec": (str, None), "max_bytes": (int, 20000)},
    "blame": {"path": (str, None), "max_results": (int, 200)},
    "wc": {"path": (str, None)},
    "sha256": {"path": (str, None)},
    "glob": {"pattern": (str, None), "max_results": (int, 200)},
    "read": {"path": (str, None), "offset": (int, 0), "max_bytes": (int, 20000)},
}


@contextlib.contextmanager
def in_worktree(cap: ModuleType, target: object) -> Generator[None]:
    """Work inside `target` for one call, only if it is in `git worktree list` of the server's own repo."""
    if type(target) is not str or not target or "\0" in target:
        raise cap.RefusalError("capability_args_invalid", "worktree must be a path string")
    done = cap.run(cap.GIT + ["worktree", "list", "--porcelain"], Path.cwd())
    if done.returncode:
        raise cap.RefusalError("capability_no_repo", "cwd is not inside a git work tree")
    listed = {os.path.realpath(x[len("worktree ") :]) for x in done.stdout.splitlines() if x.startswith("worktree ")}
    if os.path.realpath(target) not in listed:
        raise cap.RefusalError("capability_path_denied", "worktree is not in git worktree list")
    old = os.getcwd()
    os.chdir(target)
    try:
        yield
    finally:
        os.chdir(old)


def scan(path: Path) -> tuple[int, int, str]:
    """(newline count, byte count, sha256) of a file, streamed."""
    lines = size = 0
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            lines += chunk.count(b"\n")
            size += len(chunk)
            digest.update(chunk)
    return lines, size, digest.hexdigest()


def rel_of(cap: ModuleType, root: Path, rel: str) -> tuple[Path, str]:
    """safe_path plus the repo-relative string."""
    full = cap.safe_path(root, rel)
    return full, str(full.relative_to(root))


def inspect(cap: ModuleType, orig: Tool, raw: object) -> Result:
    """repo.inspect with show, blame, wc, sha256, glob and read-with-offset; every other call goes to the original."""
    as_dict = cast("dict[str, Any]", raw)
    body = dict(as_dict) if isinstance(raw, dict) else {}
    op = body.get("op")
    if op not in OPS and not (op == "read" and "offset" in body):
        return orig(as_dict)
    body.pop("op")
    a = cap.check(body, SPECS[op])
    root = cap.repo_root()
    if op == "show":
        ref, sep, rel = a["spec"].partition(":")
        if not sep:
            raise cap.RefusalError("capability_args_invalid", "spec must be <ref>:<path>")
        if not cap.REF.match(ref):
            raise cap.RefusalError("capability_bad_ref", "ref syntax")
        _, rel = rel_of(cap, root, rel)
        done = cap.run(cap.GIT + ["show", f"{ref}:{rel}"], root)
        text, cut = cap.clip(done.stdout, cap.bounded(a["max_bytes"], 1, 65536, "max_bytes"))
        return done.returncode, {"text": text, "truncated": cut}, [{"kind": "file", "ref": f"{ref}:{rel}"}]
    if op == "blame":
        _, rel = rel_of(cap, root, a["path"])
        done = cap.run(cap.GIT + ["blame", "--", rel], root)
        limit = cap.bounded(a["max_results"], 1, 1000, "max_results")
        return done.returncode, {"lines": done.stdout.splitlines()[:limit]}, [{"kind": "file", "ref": rel}]
    if op in ("wc", "sha256"):
        full, rel = rel_of(cap, root, a["path"])
        lines, size, digest = scan(full)
        found: dict[str, Any] = {"lines": lines, "bytes": size} if op == "wc" else {"sha256": digest, "bytes": size}
        return 0, found, [{"kind": "file", "ref": rel, "sha256": digest}]
    if op == "glob":
        pattern: str = a["pattern"]
        parts: list[str] = pattern.split("/")
        if not pattern or "\0" in pattern or pattern.startswith((":", "/")) or ".." in parts:
            raise cap.RefusalError("capability_path_denied", "pattern must be a repo-relative glob")
        fixed: list[str] = list(itertools.takewhile(lambda part: not any(ch in part for ch in "*?["), parts))
        cap.safe_path(root, "/".join(fixed) or ".")
        done = cap.run(cap.GIT + ["ls-files", "--", ":(glob)" + pattern], root)
        return done.returncode, {"paths": done.stdout.splitlines()[: cap.bounded(a["max_results"], 1, 1000, "n")]}, []
    full, rel = rel_of(cap, root, a["path"])
    with full.open("rb") as handle:
        handle.seek(cap.bounded(a["offset"], 0, 1 << 40, "offset"))
        data = handle.read(cap.bounded(a["max_bytes"], 1, 65536, "max_bytes"))
    evidence = [{"kind": "file", "ref": rel, "sha256": hashlib.sha256(data).hexdigest()}]
    return 0, {"text": data.decode("utf-8", "replace")}, evidence


def named_commands(cap: ModuleType) -> dict[str, dict[str, Any]]:
    """The `named_commands` table of capabilities/profiles.json: name -> {argv: [...], params: {placeholder: type}}."""
    try:
        data = json.loads((cap.ROOT / "capabilities" / "profiles.json").read_text(encoding="utf-8"))
        table: dict[str, dict[str, Any]] = data["named_commands"]
        for entry in table.values():
            assert all(type(t) is str for t in entry["argv"]) and all(type(v) is str for v in entry["params"].values())
        return table
    except (OSError, ValueError, KeyError, TypeError, AttributeError, AssertionError):
        raise cap.RefusalError("capability_profiles_invalid", "profiles.json has no valid named_commands") from None


def cmd_run(cap: ModuleType, raw: object) -> Result:
    """Run one named command from profiles.json: typed placeholders only, no shell, sandboxed like tests.run."""
    a = cap.check(raw, {"name": (str, None), "args": (dict, {})})
    entry = named_commands(cap).get(a["name"])
    if entry is None:
        raise cap.RefusalError("capability_args_invalid", "name is not declared in profiles.json named_commands")
    params: dict[str, str] = entry["params"]
    if set(a["args"]) != set(params):
        raise cap.RefusalError("capability_args_invalid", f"args must be exactly {sorted(params)}")
    root = cap.repo_root()
    values: dict[str, str] = {}
    for key, kind in params.items():
        value = a["args"][key]
        if type(value) is not str:
            raise cap.RefusalError("capability_args_invalid", f"{key} must be str")
        if kind == "repo_path":
            values[key] = "./" + rel_of(cap, root, value)[1]  # "./" so a name can never read as an option
        elif kind == "ref" and cap.REF.match(value):
            values[key] = value
        else:
            raise cap.RefusalError("capability_bad_ref" if kind == "ref" else "capability_profiles_invalid", key)
    try:
        argv = [values[t[1:-1]] if t[:1] == "{" and t[-1:] == "}" else t for t in entry["argv"]]
    except KeyError:
        raise cap.RefusalError("capability_profiles_invalid", "unknown named command placeholder") from None
    env = {k: os.environ[k] for k in ("PATH", "LANG", "TMPDIR") if k in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        with tempfile.TemporaryDirectory() as home:
            env["HOME"] = os.path.realpath(home)
            done = cap.run(cap.sandboxed(argv, root, env["HOME"]), root, env=env, timeout=60)
        status, out, err, timed_out = done.returncode, done.stdout, done.stderr, False
    except subprocess.TimeoutExpired:
        status, out, err, timed_out = 124, "", "", True
    result = {
        "name": a["name"],
        "timed_out": timed_out,
        "stdout_tail": out[-4000:],
        "stderr_tail": err[-4000:],
        "output_sha256": hashlib.sha256((out + err).encode()).hexdigest(),
    }
    return status, result, [{"kind": "command", "ref": a["name"]}]


def install(cap: ModuleType, tools: dict[str, Tool]) -> None:
    """Give every repo tool the optional `worktree` argument, extend repo.inspect, and register cmd.run."""

    def with_worktree(fn: Tool) -> Tool:
        @functools.wraps(fn)
        def tool(raw: object) -> Result:
            as_dict = cast("dict[str, Any]", raw)
            if isinstance(raw, dict) and "worktree" in raw:
                body = dict(as_dict)
                with in_worktree(cap, body.pop("worktree")):
                    return fn(body)
            return fn(as_dict)

        return tool

    original = tools["repo.inspect"]

    def repo_inspect(raw: object) -> Result:
        """Read-only repository inspection: read (offset), list, grep, status, log, show, blame, wc, sha256, glob."""
        return inspect(cap, original, raw)

    def run_named(raw: object) -> Result:
        """Run one named command from profiles.json with typed repo_path/ref arguments (sandboxed, no network)."""
        return cmd_run(cap, raw)

    tools["repo.inspect"] = repo_inspect
    tools["cmd.run"] = run_named
    for name in list(tools):
        tools[name] = with_worktree(tools[name])
