#!/usr/bin/env python3
"""Launch a Claude worker under the pinned OS sandbox and preserve its exit status."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from contextlib import nullcontext
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.sandbox.render_settings import render_settings

SRT_VERSION = "0.0.65"
DRIVER_SCHEMA = {
    "type": "object",
    "properties": {
        "outcome": {"type": "string", "enum": ["done", "skipped", "failed"]},
        "evidence": {"type": "string"},
        "final_report": {
            "type": ["object", "null"],
            "properties": {
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "label": {"type": "string", "enum": ["verified", "inferred", "guess"]},
                            "source": {"type": "string"},
                        },
                        "required": ["text", "label", "source"],
                        "additionalProperties": False,
                    },
                },
                "did_not_verify": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item": {"type": "string"},
                            "tag": {"type": "string", "enum": ["resolved", "unverifiable"]},
                            "reason": {"type": "string"},
                        },
                        "required": ["item", "tag", "reason"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["claims", "did_not_verify"],
            "additionalProperties": False,
        },
    },
    "required": ["outcome", "evidence", "final_report"],
    "additionalProperties": False,
}


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


def role_tools(role: str) -> tuple[str, str]:
    """Use the installed agent's tool allowlist for a driver worker."""
    if re.fullmatch(r"[a-z][a-z0-9-]{0,60}", role) is None:
        raise ValueError("driver role is invalid")
    source = Path(__file__).resolve().parents[2] / "agents" / f"{role}.md"
    if not source.is_file():
        raise ValueError("driver role instructions are missing")
    lines = source.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError("driver role frontmatter is invalid")
    frontmatter = lines[1 : lines.index("---", 1)]
    fields = dict(line.split(":", 1) for line in frontmatter if ":" in line)
    allowed = fields.get("tools", "").strip()
    denied = fields.get("disallowedTools", "").strip()
    if not allowed:
        raise ValueError("driver role has no tool allowlist")
    if "mcp__plugin_coderails_cap-" in allowed:
        denied += ", Bash, Read, Grep, Glob, WebFetch, Write, Edit, NotebookEdit"
    return allowed, ", ".join(part for part in ("Agent", "Task", denied) if part)


def launch(worktree: str, prompt_file: str, model: str, *, driver: bool = False, role: str = "loop-worker") -> int:
    """Prepare containment, acquire credentials externally, and stream the pinned child."""
    if not Path(worktree).is_dir():
        raise ValueError(f"worktree is not an existing directory: {worktree}")
    if not Path(prompt_file).is_file():
        raise ValueError(f"prompt_file is not an existing file: {prompt_file}")
    if not driver:
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
    ]
    if driver:
        allowed, denied = role_tools(role)
        arguments.extend(
            [
                "--output-format",
                "stream-json",
                "--verbose",
                "--json-schema",
                json.dumps(DRIVER_SCHEMA, sort_keys=True),
                "--disallowedTools",
                denied,
                "--allowedTools",
                allowed,
            ]
        )
    else:
        arguments.append(Path(prompt_file).read_text().rstrip("\n"))
    arguments.extend(["--model", model, "--dangerously-skip-permissions"])
    header = (
        f"spawn-sandboxed-worker: npx --yes @anthropic-ai/sandbox-runtime@{SRT_VERSION} "
        f"--settings {settings} claude -p <{prompt_file}> --model {model} --dangerously-skip-permissions\n"
    )
    with (scratch / "worker.log").open("wb") as log:
        if not driver:
            log.write(header.encode())
            log.flush()
            print(header, end="", flush=True)
        with Path(prompt_file).open("rb") if driver else nullcontext(None) as worker_input:
            child = subprocess.Popen(
                arguments,
                cwd=worktree,
                env=environment,
                stdin=worker_input,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL if driver else subprocess.STDOUT,
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
        if arguments[:1] == ["--driver"] and len(arguments) in {4, 5}:
            return launch(*arguments[1:4], driver=True, role=arguments[4] if len(arguments) == 5 else "loop-worker")
        if len(arguments) != 3:
            raise ValueError(f"expected 3 args (worktree prompt_file model), got {len(arguments)}")
        return launch(*arguments)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"spawn-sandboxed-worker: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
