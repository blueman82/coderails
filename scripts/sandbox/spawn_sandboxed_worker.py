#!/usr/bin/env python3
"""Launch a Claude worker under the pinned OS sandbox, import its branch and push it; preserve its exit status.

The worker never sees the primary repository, the real HOME or any inherited secret. The launcher:
  1. clones the worktree (`git clone --no-hardlinks`) into a per-worker scratch directory and runs the worker there,
     so the primary .git (refs, hooks, config) is not writable at all;
  2. rebuilds the child environment from an allowlist (PATH, LANG, TERM, the owner-provisioned worker credential,
     an isolated HOME/CLAUDE_CONFIG_DIR/XDG_*/TMPDIR under the scratch dir); no GH_TOKEN, no `gh auth token`, and
     CODERAILS_HEADLESS_RUN is never passed;
  3. after a clean exit imports exactly the worker's branch (fast-forward only; any other moved branch, including
     main/master, is refused as branch_import_refused) and pushes it from outside the sandbox.
Cooperating-agent safeguard, not absolute isolation: this launcher is trusted, reads under HOME stay possible, and
github.com + api.anthropic.com remain reachable. The scratch dir (clone, worker.log) is left in place for audit.
"""

from __future__ import annotations

import contextlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import IO

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.lib.trace_row import append_row
from scripts.sandbox.containment import SRT_VERSION, worker_credential
from scripts.sandbox.render_settings import render_settings

PROTECTED = ("main", "master")
PASS_THROUGH = ("PATH", "LANG", "TERM")
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


def import_and_push(worktree: str, clone: Path, branch: str, before: dict[str, str]) -> None:
    """Fast-forward the worktree branch to the clone's, refusing any other moved branch; then push it."""
    after = branch_heads(clone)
    moved = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
    other = [name for name in moved if name != f"refs/heads/{branch}"]
    if other:
        raise refuse("branch_import_refused", f"worker moved {', '.join(other)}; only {branch} may change")
    if not moved:
        return
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
    import_and_push(worktree, clone, branch, before)
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
