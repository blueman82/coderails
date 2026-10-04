#!/usr/bin/env python3
"""Claude-local loop detection, state ownership, locks, and atomic replacement."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.agentic_loop_path import resolve_path
from hooks.scripts.lib.discipline_common import content, records, tool_uses

LOOP_STOP_VOCAB = "hard-stop|approval-gate|awaiting-input|complete"


def log(message: str) -> None:
    """Append one escaped audit record, without creating missing log directories."""
    path = Path(os.environ.get("CLAUDE_DISCIPLINE_LOG", str(Path.home() / ".claude/discipline.log")))
    message = message.replace("\r", r"\r").replace("\n", r"\n")
    with suppress(OSError), path.open("a", encoding="utf-8") as stream:
        stream.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {message}\n")


def read_state(path: Path) -> dict[str, Any]:
    """Read object-shaped state, returning empty on unreadable or malformed input."""
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def atomic_progress_update(
    path: Path, update: Callable[[dict[str, Any]], dict[str, Any]], create: bool = False
) -> bool:
    """Serialize one provider-local read, transform, and atomic file replacement.

    With `create`, an absent file is read as `{}` so the lock serialises the create-or-exists decision.
    """
    if create:
        with suppress(OSError):
            path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file() and not create:
        return False
    lock = Path(f"{path}.lock")
    attempts = int(os.environ.get("CLAUDE_HOOK_MAX_ATTEMPTS", "5"))
    delay = float(os.environ.get("CLAUDE_HOOK_SLEEP_S", "0.3"))
    for attempt in range(attempts):
        try:
            lock.mkdir()
            break
        except OSError:
            if attempt + 1 < attempts:
                time.sleep(delay)
    else:
        return False
    temporary = ""
    try:
        state: object = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        if not isinstance(state, dict):
            return False
        proposed = update(cast(dict[str, Any], state))
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, prefix=f"{path.name}.tmp.", delete=False, encoding="utf-8"
        ) as stream:
            temporary = stream.name
            json.dump(proposed, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
        return True
    except (OSError, ValueError, TypeError, KeyError):
        return False
    finally:
        if temporary:
            with suppress(OSError):
                Path(temporary).unlink()
        with suppress(OSError):
            lock.rmdir()


def count_invocations(transcript: str) -> tuple[int, str, int]:
    """Count native Skill and slash-command loop starts with parse diagnostics."""
    try:
        total = sum(bool(line.strip()) for line in Path(transcript).read_text().splitlines())
    except OSError:
        return 0, "read_error", 0
    entries = records(transcript)
    count = 0
    for record in entries:
        for tool in tool_uses(record):
            data: object = tool.get("input")
            if tool.get("name") == "Skill" and isinstance(data, dict):
                name: object = cast(dict[str, Any], data).get("skill")
                count += int(isinstance(name, str) and bool(re.search(r"(^|:)agentic-loop$", name)))
        value = content(record)
        if record.get("type") == "user" and isinstance(value, str):
            names = re.findall(r"<command-name>/?([^<\n]+)</command-name>", value)
            count += sum(bool(re.search(r"(^|:)agentic-loop$", name.strip())) for name in names)
    skipped = total - len(entries)
    return count, "all_lines_malformed" if total and not entries else "", skipped


def stable_invocations(transcript: str) -> int:
    """Retry transcript reads and log recovered or exhausted parse diagnostics."""
    previous, count, max_skipped = -1, 0, 0
    seen_reason, last_reason = "", ""
    attempts = int(os.environ.get("CLAUDE_HOOK_MAX_ATTEMPTS", "5"))
    delay = float(os.environ.get("CLAUDE_HOOK_SLEEP_S", "0.3"))
    used = 0
    for used in range(1, attempts + 1):
        count, last_reason, skipped = count_invocations(transcript)
        max_skipped = max(max_skipped, skipped)
        if count == previous and not last_reason:
            break
        previous = count
        seen_reason = last_reason or seen_reason
        if used < attempts:
            time.sleep(delay)
    if seen_reason or max_skipped:
        outcome = "exhausted" if last_reason else "recovered"
        suffix = f" skipped_malformed={max_skipped}" if max_skipped else ""
        log(f"hook=als_count_invocations reason={seen_reason or 'none'} attempts={used} outcome={outcome}{suffix}")
    return count


@dataclass
class LoopState:
    """Session-owned progress and invocation ordinal used by all Claude guards."""

    path: Path
    session: str
    invocations: int
    data: dict[str, Any]

    @property
    def owned(self) -> bool:
        """Report whether progress belongs to this invocation's session."""
        return self.data.get("schema_version") == 3 and self.data.get("session_id") == self.session

    @property
    def rearmed(self) -> bool:
        """Report a loop invocation newer than the completion ordinal."""
        raw = str(self.data.get("completed_marker", 0))
        marker = int(raw) if raw.isdigit() else 0
        return self.invocations > marker

    @property
    def complete(self) -> bool:
        """Report session-owned completion that has not been rearmed."""
        return self.data.get("status") == "complete" and self.owned and not self.rearmed


def load_progress(cwd: str, session: str, invocations: int) -> LoopState:
    """Read the session's resolved progress and retain its invocation count."""
    path = resolve_path(cwd, session)
    return LoopState(path, session, invocations, read_state(path))


def loop_active_incomplete(transcript: str, cwd: str, session: str) -> bool:
    """Return whether a native loop invocation remains active for this session."""
    count = stable_invocations(transcript)
    return count > 0 and not load_progress(cwd, session, count).complete


def unstubbed_grace(state: LoopState, hook: str) -> bool:
    """Release only an absent-file block already logged at this invocation ordinal."""
    if state.path.is_file():
        return False
    path = Path(os.environ.get("CLAUDE_DISCIPLINE_LOG", str(Path.home() / ".claude/discipline.log")))
    try:
        lines = path.read_text()
    except OSError:
        return False
    prefix = f"hook=loop_state_guard session={state.session} invocations={state.invocations} "
    if re.search(re.escape(prefix) + r".*reason=absent blocked=1", lines):
        log(f"hook={hook} session={state.session} invocations={state.invocations} unstubbed_grace=released blocked=0")
        return True
    return False


def stop_category(text: str) -> str:
    """Return the last declaration's category after validating a complete marker."""
    if not re.search(rf"^\s*LOOP-STOP:\s*({LOOP_STOP_VOCAB})([^a-z0-9]|$)", text, re.I | re.M):
        return ""
    matches = re.findall(rf"LOOP-STOP:\s*({LOOP_STOP_VOCAB})", text, re.I)
    return matches[-1] if matches else ""


def mark_complete(cwd: str, session: str) -> bool:
    """Stamp completion with this session's actual native loop-invocation ordinal."""
    projects = Path(os.environ.get("CLAUDE_PROJECTS_DIR", str(Path.home() / ".claude/projects")))
    transcript = next((path for path in sorted(projects.glob(f"*/{session}.jsonl")) if path.is_file()), None)
    if transcript is None or not (count := stable_invocations(str(transcript))):
        return False

    def stamp(state: dict[str, Any]) -> dict[str, Any]:
        if state.get("schema_version") != 3 or state.get("session_id") != session:
            raise ValueError("completion requires current state owned by this session")
        return {**state, "status": "complete", "completed_marker": count}

    return atomic_progress_update(resolve_path(cwd, session), stamp)


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "mark-complete":
        print("usage: loop_state_common.py mark-complete <cwd> <session_id>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(0 if mark_complete(sys.argv[2], sys.argv[3]) else 1)
