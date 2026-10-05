"""Content-free, fail-open JSONL telemetry for hook invocations (shared byte-identically by both providers).

Rows carry hook name, duration, exit cause and open-fd count only. Never prompt, payload or exception text.
"""

from __future__ import annotations

import errno
import json
import os
import signal
import sys
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

RESOURCE_ERRNOS = frozenset({errno.EMFILE, errno.ENFILE, errno.EAGAIN, errno.ENOMEM})
DIAGNOSTIC_HINT = "~/Library/Logs/DiagnosticReports (macOS crash reports: look for python*.ips near this ts)"
RESOURCE_NOTICE = "Host resource exhaustion (for example too many open files) hit this hook; not a graph-state fault."


def telemetry_dir() -> Path:
    """Discipline-log directory, overridable for tests."""
    for name in ("CODERAILS_HOOK_TELEMETRY_DIR",):
        if os.environ.get(name):
            return Path(os.environ[name])
    for name in ("CLAUDE_DISCIPLINE_LOG", "CODERAILS_DISCIPLINE_LOG"):
        if os.environ.get(name):
            return Path(os.environ[name]).parent
    return Path(os.environ.get("PLUGIN_DATA") or Path.home() / ".claude")


def open_fds() -> int | None:
    """Count this process's open descriptors, excluding the listing handle; None if unknowable."""
    for path in ("/dev/fd", "/proc/self/fd"):
        try:
            return len(os.listdir(path)) - 1
        except OSError:
            continue
    return None


def classify_returncode(returncode: int) -> str:
    """Negative child returncode means killed by a signal (native crash/abort)."""
    return "native_signal" if returncode < 0 else ("ok" if returncode == 0 else "child_exit")


def record(hook: str, cause: str, duration_ms: int = 0, exit_code: int | None = None, **extra: object) -> None:
    """Append one row; any failure is swallowed so telemetry can never break a hook."""
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hook": hook,
        "cause": cause,
        "exit": exit_code,
        "duration_ms": duration_ms,
        "open_fds": open_fds(),
        "pid": os.getpid(),
        **extra,
    }
    try:
        directory = telemetry_dir()
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "hook_telemetry.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row) + "\n")
    except (OSError, ValueError):
        pass


def note_child(hook: str, returncode: int) -> None:
    """Record a child killed by a signal (e.g. SIGABRT) with the macOS crash-report hint."""
    if returncode >= 0:
        return
    try:
        name = signal.Signals(-returncode).name
    except ValueError:
        name = f"SIG{-returncode}"
    record(hook, "native_signal", exit_code=returncode, signal=name, diagnostic_hint=DIAGNOSTIC_HINT)


def child_failed(hook: str, returncode: int) -> bool:
    """Record a signal-killed child, then report whether the child failed at all."""
    note_child(hook, returncode)
    return returncode != 0


def run(hook: str, main: Callable[[], int]) -> int:
    """Run a hook main(), recording one row; resource errors are reported and fail open."""
    start = time.monotonic()

    def elapsed() -> int:
        return int((time.monotonic() - start) * 1000)

    def on_term(_signum: int, _frame: object) -> None:
        record(hook, "timeout", elapsed(), 143)
        os._exit(143)

    with suppress(ValueError, OSError):
        signal.signal(signal.SIGTERM, on_term)
    try:
        code = main()
    except SystemExit as exit_:
        code = exit_.code if isinstance(exit_.code, int) else (0 if exit_.code is None else 1)
        record(hook, "ok" if code == 0 else "exit", elapsed(), code)
        raise
    except OSError as error:
        if error.errno in RESOURCE_ERRNOS:
            record(hook, "resource", elapsed(), 0, errno=errno.errorcode.get(error.errno or 0, "?"))
            print(RESOURCE_NOTICE, file=sys.stderr)
            return 0
        record(hook, "exception", elapsed(), 1, error=type(error).__name__)
        raise
    except Exception as error:
        record(hook, "exception", elapsed(), 1, error=type(error).__name__)
        raise
    code = code or 0
    record(hook, "ok" if code == 0 else "exit", elapsed(), code)
    return code
