#!/usr/bin/env python3
"""Launch a Claude worker under the pinned OS sandbox, check its scope, import its branch and push it.

The worker never sees the primary repository or inherited environment secrets. The launcher:
  1. clones the worktree (`git clone --no-hardlinks`) into a per-worker scratch directory and runs the worker there,
     so the primary .git (refs, hooks, config) is not writable at all;
  2. rebuilds the child environment from an allowlist with a scratch HOME and dedicated worker credential;
  3. after a clean exit checks each commit against the graph unit manifest and scans new objects for known secrets,
     then imports exactly the worker's branch (fast-forward only) and pushes it outside the sandbox.
The launcher is trusted and reads under the real HOME remain possible. GitHub egress is blocked inside the sandbox;
api.anthropic.com remains reachable. The scratch dir (clone, worker.log) is left in place for audit.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import IO, Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.lib.agentic_loop_path import resolve_path
from hooks.scripts.lib.graph_dispatch import authorize_dispatch
from hooks.scripts.lib.loop_state_common import read_state
from hooks.scripts.lib.trace_row import append_row
from scripts.lib import manifest_policy
from scripts.sandbox.containment import SRT_VERSION, worker_credential
from scripts.sandbox.render_settings import render_settings

PROTECTED = ("main", "master")
PASS_THROUGH = ("PATH", "LANG", "TERM")
SECRET_PATTERNS = tuple(
    (name, re.compile(regex))
    for name, regex in (
        ("an Anthropic key", r"sk-ant-[A-Za-z0-9_-]{20,}"),
        ("a GitHub token", r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
        ("an AWS access key id", r"AKIA[0-9A-Z]{16}"),
        ("a private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    )
)
GIT_SAFE = ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null"]  # the clone's config is worker-written


def dispatch_guard(worktree: str, prompt_file: str, model: str) -> None:
    """Run the same pre-dispatch decision before creating scratch or launching a worker."""
    session = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not session:
        return
    guard = Path(__file__).resolve().parents[2] / "hooks/scripts/loop_dispatch_guard.py"
    if not guard.is_file():
        raise ValueError(f"loop dispatch guard not found: {guard}")
    command = shlex.join(["scripts/sandbox/spawn_sandboxed_worker.py", worktree, prompt_file, model])
    payload = {"tool_name": "Bash", "session_id": session, "cwd": worktree, "tool_input": {"command": command}}
    result = subprocess.run(
        [sys.executable, str(guard)], input=json.dumps(payload), capture_output=True, text=True, check=True
    )
    if not result.stdout.strip():
        return
    response = json.loads(result.stdout)
    output = response.get("hookSpecificOutput", {})
    if output.get("permissionDecision") == "deny":
        raise ValueError(str(output.get("permissionDecisionReason", "loop dispatch denied")))


def git(repo: str | Path, *arguments: str, hardened: bool = False) -> str:
    """Run git in `repo` and return stdout; `hardened` (used for the clone) ignores worker-written fsmonitor/hooks."""
    command = ["git", *(GIT_SAFE if hardened else []), "-C", str(repo), *arguments]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError(f"git {arguments[0]} failed in {repo}: {result.stderr.strip()}")
    return result.stdout.strip()


def refuse(code: str, detail: str) -> ValueError:
    """Trace a refusal under its stable reason code and return the error to raise."""
    trace("refused", code)
    return ValueError(f"{code}: {detail}")


def trace(outcome: str, code: str) -> None:
    """Append one fail-open trace row for this launcher run (needs a session id in the environment)."""
    session = os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CODEX_THREAD_ID")
    if session:
        append_row("sandbox_launch", outcome, code, session)


def branch_heads(clone: Path) -> dict[str, str]:
    """refs/heads name -> object id of the clone."""
    rows = git(clone, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads", hardened=True).splitlines()
    return dict(row.split(" ", 1) for row in rows)


def declared_manifest(worktree: str, prompt_file: str) -> list[str] | None:
    """Bind a graph worker's declared scope to the exact active U3 envelope; None outside a graph session."""
    session = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not session:
        return None
    path = resolve_path(worktree, session)
    state = read_state(path)
    if "graph" not in state:
        return None
    request = authorize_dispatch(path, session, Path(prompt_file).read_text(), "coderails:loop-worker")
    match = re.fullmatch(r"U3\[([^]]+)\]", request["node_id"])
    if not match:
        raise refuse("branch_import_refused", "sandbox launcher requires a U3 implementation envelope")
    raw_units = state.get("work_units")
    units = cast(dict[str, Any], raw_units) if isinstance(raw_units, dict) else {}
    raw_unit = units.get(match[1])
    unit = cast(dict[str, Any], raw_unit) if isinstance(raw_unit, dict) else {}
    raw_manifest = unit.get("manifest")
    manifest = cast(list[object], raw_manifest) if isinstance(raw_manifest, list) else []
    if not manifest or any(not isinstance(item, str) or not item for item in manifest):
        raise refuse("branch_import_refused", f"unit {match[1]} has no usable manifest")
    return cast(list[str], manifest)


def worker_environment(scratch: Path, credential: tuple[str, str]) -> dict[str, str]:
    """The allowlisted child environment: isolated dirs under scratch plus the worker credential, nothing inherited."""
    home = scratch / "home"
    dirs = {
        "HOME": home,
        "CLAUDE_CONFIG_DIR": home / ".claude",
        "XDG_CONFIG_HOME": scratch / "xdg-config",
        "XDG_CACHE_HOME": scratch / "xdg-cache",
        "XDG_DATA_HOME": scratch / "xdg-data",
        "XDG_STATE_HOME": scratch / "xdg-state",
        "TMPDIR": scratch / "tmp",
    }
    for path in dirs.values():
        path.mkdir(parents=True)
    environment = {name: os.environ[name] for name in PASS_THROUGH if name in os.environ}
    environment.update({name: str(path) for name, path in dirs.items()})
    environment["npm_config_cache"] = str(Path.home() / ".npm")  # npx runs with the isolated HOME: keep the pin cache
    environment[credential[0]] = credential[1]
    return environment


def stream_child(arguments: list[str], cwd: str, env: dict[str, str], log: IO[bytes]) -> int:
    """Run the pinned child, tee its output to the log and stdout, and return its exit status."""
    child = subprocess.Popen(arguments, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if child.stdout is None:
        raise RuntimeError("sandbox stdout pipe was not created")
    while True:
        chunk = os.read(child.stdout.fileno(), 65536)
        if not chunk:
            break
        log.write(chunk)
        log.flush()
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
    code = child.wait()
    return code if code >= 0 else 128 - code


def committed_secret(clone: Path, old: str | None, new: str, credential_value: str) -> str | None:
    """Scan every new Git object, including binary blobs and intermediate commits, before publication."""
    revisions = f"{old}..{new}" if old else new
    objects = git(clone, "rev-list", "--objects", revisions, hardened=True).splitlines()
    for row in objects:
        oid = row.split(" ", 1)[0]
        result = subprocess.run(
            ["git", *GIT_SAFE, "-C", str(clone), "cat-file", "-p", oid], capture_output=True, check=False
        )
        if result.returncode:
            raise refuse("branch_import_refused", f"cannot inspect worker object {oid}")
        data = result.stdout
        if credential_value and credential_value.encode() in data:
            return "the worker credential"
        for name, pattern in SECRET_PATTERNS:
            if re.search(pattern.pattern.encode(), data):
                return name
    return None


def import_and_push(
    worktree: str,
    clone: Path,
    branch: str,
    before: dict[str, str],
    credential_value: str = "",
    manifest: list[str] | None = None,
) -> None:
    """Fast-forward the worktree branch to the clone's, refusing any other moved branch or committed secret; push it."""
    after = branch_heads(clone)
    moved = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
    other = [name for name in moved if name != f"refs/heads/{branch}"]
    if other:
        raise refuse("branch_import_refused", f"worker moved {', '.join(other)}; only {branch} may change")
    if not moved:
        return
    ref = f"refs/heads/{branch}"
    if manifest is not None:
        commits = git(clone, "rev-list", "--reverse", f"{before[ref]}..{after[ref]}", hardened=True).splitlines()
        for commit in commits:
            diff = git(clone, "diff", "--raw", "-z", "-M", before[ref], commit, hardened=True)
            verdict = manifest_policy.check(manifest_policy.parse_raw_z(diff), {}, manifest)
            if not verdict["ok"]:
                violation = verdict["violations"][0]
                raise refuse("branch_import_refused", f"{violation['code']}: {violation['path']}; nothing pushed")
    found = committed_secret(clone, before.get(ref), after[ref], credential_value)
    if found:
        raise refuse("branch_import_refused", f"secret found in the worker's commits ({found}); nothing pushed")
    private = f"refs/coderails/import/{branch}"
    try:
        git(worktree, "fetch", "--quiet", str(clone), f"+refs/heads/{branch}:{private}")
        git(worktree, "merge", "--ff-only", "--quiet", private)
    except ValueError as error:
        raise refuse("branch_import_refused", f"{branch} is not a fast-forward import: {error}") from error
    finally:
        with contextlib.suppress(ValueError):
            git(worktree, "update-ref", "-d", private)
    trace("imported", "branch_imported")
    git(worktree, "push", "--quiet", "origin", branch)  # from outside the sandbox, with the operator's own git auth
    trace("pushed", "branch_pushed")


def launch(worktree: str, prompt_file: str, model: str) -> int:
    """Prepare containment, run the pinned child on a scratch clone, then import and push its branch."""
    if not Path(worktree).is_dir():
        raise ValueError(f"worktree is not an existing directory: {worktree}")
    if not Path(prompt_file).is_file():
        raise ValueError(f"prompt_file is not an existing file: {prompt_file}")
    dispatch_guard(worktree, prompt_file, model)
    manifest = declared_manifest(worktree, prompt_file)
    try:
        branch = git(worktree, "branch", "--show-current") if git(worktree, "rev-parse", "--git-common-dir") else ""
    except ValueError as error:
        raise ValueError(f"worktree is not a git worktree (git-common-dir failed): {error}") from error
    if not branch or branch in PROTECTED:
        raise refuse(
            "branch_import_refused", f"the worktree must be on a feature branch, not {branch or 'a detached HEAD'}"
        )
    if not shutil.which("npx"):
        raise ValueError("npx not found on PATH")
    credential = worker_credential()
    if credential is None:
        raise refuse("worker_credential_missing", "provision ~/.coderails/worker_credential (mode 0600)")
    # short prefix: srt binds a unix socket at $TMPDIR/srt-mux-<pid>-0.sock and macOS limits that path to ~103 chars
    scratch = Path(tempfile.mkdtemp(prefix="sw.", dir=os.environ.get("TMPDIR", "/tmp")))
    environment = worker_environment(scratch, credential)
    clone = scratch / "clone"
    git(worktree, "clone", "--quiet", "--no-hardlinks", "--branch", branch, ".", str(clone))
    before = branch_heads(clone)
    settings = scratch / "srt-settings.json"
    render_settings(str(clone), str(scratch), str(settings))
    arguments = [
        "npx",
        "--yes",
        f"@anthropic-ai/sandbox-runtime@{SRT_VERSION}",
        "--settings",
        str(settings),
        "claude",
        "-p",
        Path(prompt_file).read_text().rstrip("\n"),
        "--model",
        model,
        "--dangerously-skip-permissions",
    ]
    header = (
        f"spawn-sandboxed-worker: npx --yes @anthropic-ai/sandbox-runtime@{SRT_VERSION} "
        f"--settings {settings} claude -p <{prompt_file}> --model {model} --dangerously-skip-permissions\n"
    )
    with (scratch / "worker.log").open("wb") as log:
        log.write(header.encode())
        log.flush()
        print(header, end="", flush=True)
        code = stream_child(arguments, str(clone), environment, log)
    if code:
        print(f"spawn-sandboxed-worker: worker exited {code}; nothing imported, work left in {clone}", file=sys.stderr)
        return code
    import_and_push(worktree, clone, branch, before, credential[1], manifest)
    return 0


def main(arguments: list[str] | None = None) -> int:
    """Dispatch a contained worker and report preparation failures."""
    arguments = sys.argv[1:] if arguments is None else arguments
    try:
        if len(arguments) != 3:
            raise ValueError(f"expected 3 args (worktree prompt_file model), got {len(arguments)}")
        return launch(*arguments)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"spawn-sandboxed-worker: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
