"""Content-free, fail-open JSONL telemetry for hook invocations (shared byte-identically by both providers).

Rows carry ts, hook, cause, exit, duration_ms, open_fds and pid, plus allow-listed content-free extras
(errno, signal, error class name, diagnostic_hint). Never prompt, payload or exception text.
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
ALLOWED_EXTRA = frozenset({"errno", "signal", "error", "diagnostic_hint"})  # content-free keys only
MAX_BYTES = 1_000_000  # ponytail: one rotated generation (.1); add more only if history is needed


def telemetry_dir() -> Path:
    """Discipline-log directory, overridable for tests."""
    if override := os.environ.get("CODERAILS_HOOK_TELEMETRY_DIR"):
        return Path(override)
    for name in ("CLAUDE_DISCIPLINE_LOG", "CODERAILS_DISCIPLINE_LOG"):
        if os.environ.get(name):
            return Path(os.environ[name]).parent
    # one file serves both providers, so pick the default home from where this copy lives
    home = Path(".coderails", "codex") if "codex" in Path(__file__).parts else Path(".claude")
    return Path(os.environ.get("PLUGIN_DATA") or Path.home() / home)


def open_fds() -> int | None:
    """Count this process's open descriptors, excluding the listing handle; None if unknowable."""
    for path in ("/dev/fd", "/proc/self/fd"):
        try:
            return len(os.listdir(path)) - 1
        except OSError:
            continue
    return None


_denied = False


def exit_cause(code: int) -> str:
    """Name a clean-return exit code: a deny decision (exit 0 plus deny JSON), ok, block (2) or other."""
    return "deny" if _denied and code == 0 else "ok" if code == 0 else "block" if code == 2 else "exit"


def mark_deny() -> None:
    """Called by deny(): the hook is emitting a deny decision, so run() records cause deny rather than ok."""
    global _denied
    _denied = True


def record(hook: str, cause: str, duration_ms: int = 0, exit_code: int | None = None, **extra: object) -> None:
    """Append one row; never raises, so telemetry can never break a hook."""
    try:
        row = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "hook": hook,
            "cause": cause,
            "exit": exit_code,
            "duration_ms": duration_ms,
            "open_fds": open_fds(),
            "pid": os.getpid(),
            **{key: value for key, value in extra.items() if key in ALLOWED_EXTRA and value is not None},
        }
        directory = telemetry_dir()
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "hook_telemetry.jsonl"
        if target.exists() and target.stat().st_size > MAX_BYTES:
            os.replace(target, target.with_suffix(".jsonl.1"))
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row) + "\n")
    except (
        Exception
    ) as error:  # noqa: BLE001 - broad on purpose: Path.home() RuntimeError, OSError, TypeError all fail open
        with suppress(Exception):
            code = errno.errorcode.get(getattr(error, "errno", None) or 0, "-")
            if exit_code != 2:  # on exit 2 stderr IS the model-visible block reason; never pollute it
                print(f"hook_telemetry: write failed ({type(error).__name__}, errno={code})", file=sys.stderr)


def note_child(hook: str, returncode: int) -> None:
    """Record a child killed by a signal (e.g. SIGABRT) with the macOS crash-report hint."""
    if returncode >= 0:
        return
    try:
        name = signal.Signals(-returncode).name
    except ValueError:
        name = f"SIG{-returncode}"
    hint = DIAGNOSTIC_HINT if sys.platform == "darwin" else None
    record(hook, "native_signal", exit_code=returncode, signal=name, diagnostic_hint=hint)


def run(hook: str, main: Callable[[], int]) -> int:
    """Run a hook main(), recording one row; every failure is recorded and re-raised, never turned into success."""
    global _denied
    _denied = False
    start = time.monotonic()

    def elapsed() -> int:
        return int((time.monotonic() - start) * 1000)

    terminated = False

    def on_term(_signum: int, _frame: object) -> None:
        nonlocal terminated
        terminated = True
        with suppress(OSError):  # a dead stderr must not replace SystemExit(143)
            os.write(2, b"terminated by SIGTERM, likely hook timeout; action NOT gated\n")
        raise SystemExit(143)  # unwind normally so the row and buffered output are written outside the handler

    with suppress(ValueError, OSError):
        signal.signal(signal.SIGTERM, on_term)
    try:
        code = main()
    except SystemExit as exit_:
        code = exit_.code if isinstance(exit_.code, int) else (0 if exit_.code is None else 1)
        cause = "sigterm" if terminated else exit_cause(code)
        record(hook, cause, elapsed(), code)
        raise
    except OSError as error:
        if error.errno in RESOURCE_ERRNOS:
            record(hook, "resource", elapsed(), 1, errno=errno.errorcode.get(error.errno or 0, "?"))
            print(RESOURCE_NOTICE, file=sys.stderr)
            raise
        record(hook, "exception", elapsed(), 1, error=type(error).__name__)
        raise
    except Exception as error:
        record(hook, "exception", elapsed(), 1, error=type(error).__name__)
        raise
    code = code or 0
    record(hook, exit_cause(code), elapsed(), code)
    return code
