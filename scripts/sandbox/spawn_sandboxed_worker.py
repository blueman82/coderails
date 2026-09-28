#!/usr/bin/env python3
"""Launch a Claude worker under the pinned OS sandbox and preserve its exit status."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.sandbox.render_settings import render_settings

SRT_VERSION = "0.0.65"


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


def launch(worktree: str, prompt_file: str, model: str) -> int:
    """Prepare containment, acquire credentials externally, and stream the pinned child."""
    if not Path(worktree).is_dir():
        raise ValueError(f"worktree is not an existing directory: {worktree}")
    if not Path(prompt_file).is_file():
        raise ValueError(f"prompt_file is not an existing file: {prompt_file}")
    dispatch_guard(worktree, prompt_file, model)
    result = subprocess.run(
        ["git", "-C", worktree, "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=True,
    )
    primary_git = result.stdout.strip()
    for executable in ("npx", "gh"):
        if not shutil.which(executable):
            raise ValueError(f"{executable} not found on PATH")
    scratch = Path(tempfile.mkdtemp(prefix="sandbox-worker.", dir=os.environ.get("TMPDIR", "/tmp")))
    settings = scratch / "srt-settings.json"
    render_settings(worktree, str(scratch), primary_git, str(settings))
    cache = scratch / "xdg-cache"
    cache.mkdir()
    token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
    environment = os.environ.copy()
    environment.update(GH_TOKEN=token, XDG_CACHE_HOME=str(cache))
    environment.pop("CODERAILS_HEADLESS_RUN", None)
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
        child = subprocess.Popen(
            arguments, cwd=worktree, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
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
