#!/usr/bin/env python3
"""Inject native Codex skill and graph-resume context at session start."""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import cast


def read_input(timeout_seconds: float = 5.0) -> str:
    """Read available stdin bytes for at most the established hook timeout."""
    descriptor = sys.stdin.fileno()
    chunks = bytearray()
    deadline = time.monotonic() + timeout_seconds
    with suppress(OSError):
        os.set_blocking(descriptor, False)
    while (remaining := deadline - time.monotonic()) > 0:
        readable, _, _ = select.select([descriptor], [], [], remaining)
        if not readable:
            break
        try:
            chunk = os.read(descriptor, 65536)
        except BlockingIOError:
            continue
        if not chunk:
            break
        chunks.extend(chunk)
    return chunks.decode(errors="replace")


def payload_object(raw_payload: str) -> dict[str, object]:
    """Decode a hook payload, treating malformed input as an empty mapping."""
    try:
        decoded: object = json.loads(raw_payload)
    except json.JSONDecodeError:
        return {}
    return cast(dict[str, object], decoded) if isinstance(decoded, dict) else {}


def text_field(payload: dict[str, object], name: str) -> str:
    """Return a non-empty string field, or the established empty fallback."""
    value = payload.get(name)
    return value if isinstance(value, str) else ""


def git_output(arguments: list[str]) -> str:
    """Return successful Git output, or an empty string on a failed probe."""
    try:
        result = subprocess.run(["git", *arguments], capture_output=True, check=False, text=True)
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def loop_state_path(cwd: str, session_id: str) -> Path:
    """Return the canonical graph-state path, with the legacy-state fallback."""
    safe_session = session_id.replace("/", "_").replace("..", "")
    root = Path(os.environ.get("CODERAILS_AGENTIC_LOOP_DIR", str(Path.home() / ".coderails" / "agentic-loop")))
    git_dir = git_output(["-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"])
    slug_source = git_dir if git_dir.startswith("/") else cwd
    slug = slug_source.replace("/", "-")
    canonical = root / slug / safe_session / "progress.json"
    if canonical.is_file():
        return canonical
    candidates = sorted(root.glob(f"*/{safe_session}/progress.json"))
    return candidates[0] if candidates else canonical


def graph_resume(plugin_root: Path, cwd: str, session_id: str) -> str:
    """Return the established graph-resume text for a valid session and cwd."""
    if not session_id or not cwd:
        return ""
    state = loop_state_path(cwd, session_id)
    if not state.is_file():
        return f"no active graph; new graph path: {state}"
    graph = plugin_root / "skills" / "agentic-loop" / "scripts" / "graph.py"
    try:
        result = subprocess.run(
            [sys.executable, str(graph), "inspect", str(state)], capture_output=True, check=False, text=True
        )
    except OSError:
        result = None
    inspection = result.stdout.strip() if result is not None and result.returncode == 0 else ""
    return f"{state}: {inspection or 'invalid graph state; repair before dispatch'}"


def legacy_config_found(cwd: str) -> bool:
    """Return whether a startup path has legacy, but no canonical, configuration."""
    git_root = git_output(["-C", cwd, "rev-parse", "--show-toplevel"])
    if not git_root:
        return False
    probe = Path(cwd).resolve()
    root = Path(git_root)
    legacy = False
    while True:
        if (probe / ".coderails" / "workflow.config.yaml").is_file():
            return False
        if (probe / ".claude" / "workflow.config.yaml").is_file() or (
            probe / ".codex" / "workflow.config.yaml"
        ).is_file():
            legacy = True
        if probe == root or probe == probe.parent:
            return legacy
        probe = probe.parent


def main() -> int:
    """Emit the SessionStart additional-context envelope."""
    payload = payload_object(read_input())
    plugin_root = Path(os.environ.get("PLUGIN_ROOT", str(Path(__file__).resolve().parents[2])))
    skill = plugin_root / "skills" / "using-coderails" / "SKILL.md"
    cwd = text_field(payload, "cwd")
    resume = graph_resume(plugin_root, cwd, text_field(payload, "session_id"))
    if skill.is_file():
        context = (
            "Coderails is active. Load coderails-codex:using-coderails before acting, then every "
            "relevant native skill. Keep the top-level session as the orchestrator and delegate do-work "
            "tool calls with spawn_agent. "
            f"Native graph resume: {resume}"
        )
    else:
        context = (
            "Coderails is active, but its native using-coderails skill is missing at "
            f"{skill}. Report this before substantive work. Native graph resume: {resume}"
        )
    if text_field(payload, "source") == "startup" and cwd and legacy_config_found(cwd):
        context += (
            "\n\nLegacy Coderails workflow configuration found. Run $coderails-codex:init to "
            "migrate it to .coderails/workflow.config.yaml."
        )
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
