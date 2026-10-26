"""Small shared primitives for native Codex Python hooks."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import select
import stat
import subprocess
import sys
import time
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Codex ships scripts/ beside hooks/
from scripts.lib.authority_object import safe_session as safe_session  # noqa: E402

safe_id = safe_session

RESOURCE_ERRNOS = frozenset({errno.EMFILE, errno.ENFILE, errno.EAGAIN, errno.ENOMEM})
RESOURCE_MESSAGE = (
    "Host resource exhaustion (for example too many open files) prevented reading the graph state. "
    "The state is not known to be invalid: retry, and do not repair progress.json for this."
)


class HostResourceError(OSError):
    """The host could not start the graph helper; this says nothing about graph validity."""


PATCH_PATH = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.*)$|^\*\*\* Move to: (.*)$")


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


def text_field(payload: dict[str, object], name: str, default: str = "") -> str:
    """Return a string field, or the caller's established fallback."""
    value = payload.get(name)
    return value if isinstance(value, str) else default


def log(message: str) -> None:
    """Append a best-effort timestamped discipline record."""
    data_dir = Path(os.environ.get("PLUGIN_DATA", str(Path.home() / ".coderails" / "codex")))
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        log_file = Path(os.environ.get("CODERAILS_DISCIPLINE_LOG", data_dir / "discipline.log"))
        with log_file.open("a", encoding="utf-8") as output:
            output.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {message}\n")
    except OSError:
        return


def loop_root() -> Path:
    """Return the loop-state root shared with scripts/authority.py (CLAUDE_AGENTIC_LOOP_DIR wins)."""
    override = os.environ.get("CLAUDE_AGENTIC_LOOP_DIR") or os.environ.get("CODERAILS_AGENTIC_LOOP_DIR")
    return Path(override or Path.home() / ".coderails" / "agentic-loop")


def authority_path(session_id: str) -> Path | None:
    """Return <loop root>/<session_id>/authority.json, or None for an unsafe id."""
    return loop_root() / session_id / "authority.json" if safe_id(session_id) else None


def append_trace_row(
    command: str, outcome: str, reason_code: str, session_id: str, extra: dict[str, Any] | None = None
) -> bool:
    """Append one non-authoritative trace row (same fields as the Claude trace_row helper); never raises."""
    if not session_id or session_id in {"?", "."} or "/" in session_id or ".." in session_id or "\0" in session_id:
        return False
    root = loop_root()
    row: dict[str, object] = {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "session_id": session_id,
        "loop_id": (extra or {}).get("loop_id"),
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": command,
        "outcome": outcome,
        "reason_code": reason_code,
        "inputs": {
            k: hashlib.sha256(v.encode("utf-8")).hexdigest() for k, v in (extra or {}).get("inputs", {}).items()
        },
    }
    try:
        path = root / session_id / "trace.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(descriptor, (json.dumps(row, sort_keys=True) + "\n").encode("utf-8"))
        finally:
            os.close(descriptor)
    except OSError:
        return False
    return True


def continue_turn(reason: str) -> None:
    """Emit the established Stop-hook block response."""
    print(json.dumps({"decision": "block", "reason": reason}))


def deny(reason: str) -> None:
    """Emit the native PreToolUse denial envelope."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


def session_dir(session_id: str) -> Path | None:
    """Return the session-only data directory, or none for an empty identity."""
    safe_session = session_id.replace("/", "_").replace("..", "")
    if not safe_session:
        return None
    data_dir = Path(os.environ.get("PLUGIN_DATA", str(Path.home() / ".coderails" / "codex")))
    return data_dir / "sessions" / safe_session


def loop_state_path(
    cwd: str, session_id: str, *, strict: bool = False, timeout_seconds: float | None = None
) -> Path | None:
    """Find session state; strict callers refuse uncertain discovery instead of treating it as absent."""
    safe_session = session_id.replace("/", "_").replace("..", "")
    if not safe_session:
        return None
    root = Path(os.environ.get("CODERAILS_AGENTIC_LOOP_DIR") or Path.home() / ".coderails" / "agentic-loop")
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except OSError:
        if strict:
            raise
        result = None
    if strict and result is not None and result.returncode:
        if "not a git repository" not in result.stderr.lower():
            raise OSError("cannot determine graph repository")
        start = Path(cwd).resolve()
        for directory in (start, *start.parents):
            try:
                (directory / ".git").stat()
            except FileNotFoundError:
                continue
            raise OSError("Git metadata exists but graph repository discovery failed")
    if strict and result is not None and result.returncode == 0 and not result.stdout.strip():
        raise OSError("graph repository path is empty")
    source = result.stdout.strip() if result is not None and result.returncode == 0 else cwd
    canonical = root / source.replace("/", "-") / safe_session / "progress.json"

    def present(path: Path) -> bool:
        if not strict:
            return path.exists()
        try:
            mode = path.stat().st_mode
        except FileNotFoundError:
            return False
        if not stat.S_ISREG(mode):
            raise OSError("graph state path is not a regular file")
        return True

    if present(canonical):
        return canonical
    try:
        matches = sorted(
            candidate / safe_session / "progress.json"
            for candidate in root.iterdir()
            if present(candidate / safe_session / "progress.json")
        )
    except FileNotFoundError:
        matches = []
    except OSError:
        if strict:
            raise
        matches = []
    if strict and len(matches) > 1:
        raise OSError("more than one graph state matches this session")
    if strict:
        return matches[0] if matches else None
    return matches[0] if matches else canonical


def graph_path() -> Path:
    """Return the provider-local graph adapter path."""
    root = Path(os.environ.get("PLUGIN_ROOT") or Path(__file__).resolve().parents[2])
    return root / "skills" / "agentic-loop" / "scripts" / "graph.py"


def graph_output(graph: Path, *arguments: str, timeout_seconds: float | None = None) -> dict[str, object] | None:
    """Run one graph command and return its object output when valid."""
    try:
        result = subprocess.run(
            ["python3", str(graph), *arguments],
            stdout=subprocess.PIPE,
            check=False,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout_seconds,
        )
    except OSError as error:
        if error.errno in RESOURCE_ERRNOS:
            raise HostResourceError(error.errno, str(error)) from error
        return None
    if result.returncode != 0:
        return None
    try:
        decoded: object = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return cast(dict[str, object], decoded) if isinstance(decoded, dict) else None


def patch_paths(payload: dict[str, object]) -> list[str]:
    """Return target paths declared by an apply-patch payload."""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return []
    command = cast(dict[str, object], tool_input).get("command")
    if not isinstance(command, str):
        return []
    return [
        next(value for value in match.groups() if value is not None)
        for line in command.splitlines()
        if (match := PATCH_PATH.match(line))
    ]


def repo_for_path(path: Path) -> Path | None:
    """Return the owning Git worktree root for a file path when available."""
    probe = path
    while not probe.is_dir() and probe != probe.parent:
        probe = probe.parent
    try:
        result = subprocess.run(
            ["git", "-C", str(probe), "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return None
    return Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None
