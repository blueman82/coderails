#!/usr/bin/env python3
"""Narrow capability tools with strict argument schemas: `capability.py <tool> --json-args '<json>'`.

No shell is ever involved (argv lists only). Stdout is one typed JSON object; every call and every refusal appends a
fail-open trace row. Exit 0 means the tool ran (see `exit_status` for the underlying command), 2 means refused.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GIT = ["git", "-c", "core.fsmonitor=false", "--no-pager"]
REF = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._/~^@{}-]{0,99}$")
Result = tuple[int, dict[str, Any], list[dict[str, str]]]  # exit_status, result, evidence


class RefusalError(Exception):
    """A request refused before anything ran; `code` is the stable low-cardinality reason."""

    def __init__(self, code: str, detail: str = "") -> None:
        """Record the stable code and a human detail."""
        super().__init__(code)
        self.code, self.detail = code, detail


def check(raw: object, spec: dict[str, tuple[type, Any]]) -> dict[str, Any]:
    """Strict schema: object only, no unknown keys, exact types (bool is not int); None default means required."""
    if not isinstance(raw, dict):
        raise RefusalError("capability_args_invalid", "args must be an object")
    args: dict[str, Any] = dict(raw)  # pyright: ignore[reportUnknownArgumentType]
    unknown = set(args) - set(spec)
    if unknown:
        raise RefusalError("capability_args_invalid", f"unknown keys {sorted(unknown)}")
    out: dict[str, Any] = {}
    for key, (kind, default) in spec.items():
        if key not in args and default is None:
            raise RefusalError("capability_args_invalid", f"missing {key}")
        value = args.get(key, default)
        if type(value) is not kind:
            raise RefusalError("capability_args_invalid", f"{key} must be {kind.__name__}")
        out[key] = value
    return out


def bounded(value: int, low: int, high: int, name: str) -> int:
    """Refuse an integer outside [low, high]."""
    if not low <= value <= high:
        raise RefusalError("capability_args_invalid", f"{name} out of range")
    return value


def run(
    argv: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an argv list (never a shell string) and capture text output."""
    return subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
        env=env,
        timeout=timeout,
        input=stdin,
    )


def repo_root() -> Path:
    """The git work tree containing the caller's cwd; refuse outside one."""
    done = run(GIT + ["rev-parse", "--show-toplevel"], Path.cwd())
    if done.returncode:
        raise RefusalError("capability_no_repo", "cwd is not inside a git work tree")
    return Path(done.stdout.strip()).resolve()


def safe_path(root: Path, rel: str) -> Path:
    """Resolve a repo-relative path and refuse absolute paths, NUL bytes and anything resolving outside the repo."""
    if not rel or "\0" in rel or os.path.isabs(rel):
        raise RefusalError("capability_path_denied", "path must be repo-relative")
    full = (root / rel).resolve()
    if full != root and root not in full.parents:
        raise RefusalError("capability_path_denied", "path escapes the repository")
    return full


def clip(text: str, limit: int) -> tuple[str, bool]:
    """Truncate to `limit` bytes (UTF-8) and say whether it was cut."""
    data = text.encode("utf-8")
    return data[:limit].decode("utf-8", "replace"), len(data) > limit


def repo_inspect(raw: object) -> Result:
    """Read-only repository inspection: read, list, grep, status, log."""
    if not isinstance(raw, dict):
        raise RefusalError("capability_args_invalid", "args must be an object")
    body: dict[str, Any] = dict(raw)  # pyright: ignore[reportUnknownArgumentType]
    probe = body.pop("op", None)
    specs: dict[str, dict[str, tuple[type, Any]]] = {
        "read": {"path": (str, None), "max_bytes": (int, 20000)},
        "list": {"path": (str, ".")},
        "grep": {"pattern": (str, None), "path": (str, "."), "max_results": (int, 50)},
        "status": {},
        "log": {"n": (int, 10)},
    }
    if not isinstance(probe, str) or probe not in specs:
        raise RefusalError("capability_args_invalid", "unknown op")
    a = check(body, specs[probe])
    root = repo_root()
    if probe == "read":
        path = safe_path(root, a["path"])
        data = path.read_bytes()[: bounded(a["max_bytes"], 1, 65536, "max_bytes")]
        rel = str(path.relative_to(root))
        evidence = [{"kind": "file", "ref": rel, "sha256": hashlib.sha256(data).hexdigest()}]
        return 0, {"text": data.decode("utf-8", "replace")}, evidence
    if probe == "list":
        names = sorted(p.name for p in safe_path(root, a["path"]).iterdir())[:500]
        return 0, {"entries": names}, [{"kind": "dir", "ref": a["path"]}]
    if probe == "grep":
        where = str(safe_path(root, a["path"]).relative_to(root))
        limit = bounded(a["max_results"], 1, 200, "max_results")
        done = run(GIT + ["grep", "-n", "-I", "-e", a["pattern"], "--", where], root)
        return done.returncode if done.returncode > 1 else 0, {"matches": done.stdout.splitlines()[:limit]}, []
    argv = (
        ["status", "--porcelain=v1"]
        if probe == "status"
        else ["log", "--oneline", "-n", str(bounded(a["n"], 1, 50, "n"))]
    )
    done = run(GIT + argv, root)
    return done.returncode, {"lines": done.stdout.splitlines()}, []


def diff_read(raw: object) -> Result:
    """Read a unified diff between refs, with resolved commit shas as evidence."""
    a = check(raw, {"base": (str, None), "head": (str, "HEAD"), "paths": (list, []), "max_bytes": (int, 60000)})
    root = repo_root()
    evidence: list[dict[str, str]] = []
    for ref in (a["base"], a["head"]):
        if not REF.match(ref):
            raise RefusalError("capability_bad_ref", "ref syntax")
        done = run(GIT + ["rev-parse", "--verify", "-q", ref + "^{commit}"], root)
        if done.returncode:
            raise RefusalError("capability_bad_ref", "ref does not resolve")
        evidence.append({"kind": "commit", "ref": ref, "sha": done.stdout.strip()})
    paths: list[str] = []
    for item in a["paths"]:
        if not isinstance(item, str):
            raise RefusalError("capability_args_invalid", "paths must be strings")
        paths.append(str(safe_path(root, item).relative_to(root)))
    argv = GIT + ["diff", "--no-ext-diff", "--no-textconv", "--no-color", a["base"], a["head"], "--", *paths]
    done = run(argv, root)
    text, cut = clip(done.stdout, bounded(a["max_bytes"], 1, 200000, "max_bytes"))
    return (
        done.returncode,
        {"diff": text, "truncated": cut, "full_sha256": hashlib.sha256(done.stdout.encode()).hexdigest()},
        evidence,
    )


def declared_tests() -> dict[str, list[str]]:
    """The named argv lists tests.run may execute, from capabilities/profiles.json."""
    data: dict[str, Any] = json.loads((ROOT / "capabilities" / "profiles.json").read_text(encoding="utf-8"))
    return dict(data["tests"])


def tests_run(raw: object) -> Result:
    """Run one declared test command: bounded timeout, scrubbed env. Bounded execution of repo code, NOT read-only."""
    a = check(raw, {"name": (str, None), "timeout_s": (int, 300)})
    timeout = bounded(a["timeout_s"], 1, 900, "timeout_s")
    argv = declared_tests().get(a["name"])
    if argv is None:
        raise RefusalError("capability_tests_unknown_name", "name is not declared in profiles.json tests")
    root = repo_root()
    env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "TMPDIR") if k in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        done = run(argv, root, env=env, timeout=timeout)
        status, out, err, timed_out = done.returncode, done.stdout, done.stderr, False
    except subprocess.TimeoutExpired as expired:
        text = [
            x.decode("utf-8", "replace") if isinstance(x, bytes) else (x or "")
            for x in (expired.stdout, expired.stderr)
        ]
        status, out, err, timed_out = 124, text[0], text[1], True
    head = run(GIT + ["rev-parse", "HEAD"], root).stdout.strip()
    result = {
        "name": a["name"],
        "timed_out": timed_out,
        "stdout_tail": out[-4000:],
        "stderr_tail": err[-4000:],
        "output_sha256": hashlib.sha256((out + err).encode()).hexdigest(),
    }
    return status, result, [{"kind": "command", "ref": a["name"]}, {"kind": "commit", "ref": "HEAD", "sha": head}]


def pr_comment(raw: object) -> Result:
    """Post one comment on a PR of the current repo via `gh` (argv list, body on stdin)."""
    a = check(raw, {"pr": (int, None), "body": (str, None)})
    bounded(a["pr"], 1, 10_000_000, "pr")
    bounded(len(a["body"]), 1, 4000, "body length")
    done = run(["gh", "pr", "comment", str(a["pr"]), "--body-file", "-"], repo_root(), stdin=a["body"])
    return (
        done.returncode,
        {"url": done.stdout.strip(), "stderr_tail": done.stderr[-500:]},
        [{"kind": "pr", "ref": str(a["pr"])}],
    )


TOOLS: dict[str, Callable[[object], Result]] = {
    "repo.inspect": repo_inspect,
    "diff.read": diff_read,
    "tests.run": tests_run,
    "pr.comment": pr_comment,
}


def trace(tool: str, outcome: str, code: str, raw: str) -> None:
    """Append one fail-open trace row when a session id and the trace library are available."""
    session = os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("CODEX_THREAD_ID") or "?"
    try:
        from hooks.scripts.lib.trace_row import append_row
    except ImportError:  # the Codex copy ships without the Claude hook library: no trace rows there
        return
    append_row("capability", outcome, code, session, inputs={"tool": tool, "args": raw})


def main(argv: list[str]) -> int:
    """Dispatch one tool call and print its typed JSON envelope."""
    tool = argv[0] if argv else "?"
    raw = argv[2] if len(argv) == 3 else ""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        if tool not in TOOLS:
            raise RefusalError("capability_unknown_tool")
        if len(argv) != 3 or argv[1] != "--json-args":
            raise RefusalError("capability_bad_argv", "usage: <tool> --json-args '<json>'")
        try:
            parsed = json.loads(raw)
        except ValueError:
            raise RefusalError("capability_args_invalid", "args are not valid JSON") from None
        status, result, evidence = TOOLS[tool](parsed)
    except RefusalError as refusal:
        trace(tool[:40], "refused", refusal.code, raw)
        print(
            json.dumps(
                {
                    "tool": tool[:40],
                    "ok": False,
                    "exit_status": 2,
                    "ts": now,
                    "refusal": refusal.code,
                    "detail": refusal.detail,
                }
            )
        )
        return 2
    except OSError as error:
        trace(tool, "refused", "capability_io_error", raw)
        print(
            json.dumps(
                {
                    "tool": tool,
                    "ok": False,
                    "exit_status": 2,
                    "ts": now,
                    "refusal": "capability_io_error",
                    "detail": error.strerror or "",
                }
            )
        )
        return 2
    sha = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    trace(tool, "ok", tool, raw)
    print(
        json.dumps(
            {
                "tool": tool,
                "ok": True,
                "exit_status": status,
                "ts": now,
                "artifact_sha": sha,
                "evidence": evidence,
                "result": result,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
