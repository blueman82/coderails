#!/usr/bin/env python3
"""Inject the compact context manifest (lib/context_manifest.py) at Codex session start."""

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

from lib.context_manifest import session_manifest


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
    raw = read_input()
    payload = payload_object(raw)
    plugin_root = Path(os.environ.get("PLUGIN_ROOT", str(Path(__file__).resolve().parents[2])))
    cwd = text_field(payload, "cwd")
    context = session_manifest(raw, plugin_root, "coderails-codex")
    if text_field(payload, "source") == "startup" and cwd and legacy_config_found(cwd):
        context += (
            "\n\nLegacy Coderails workflow configuration found. Run $coderails-codex:init to "
            "migrate it to .coderails/workflow.config.yaml."
        )
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}))
    return 0


if __name__ == "__main__":
    try:
        from lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("inject_bootstrap", main))
