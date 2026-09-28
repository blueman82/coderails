#!/usr/bin/env python3
"""Stop only the dashboard process identified by the provider-local PID file."""

import contextlib
import os
import signal
import subprocess
import time
from pathlib import Path

PROVIDER_HOME = ".claude"


def alive(pid: int) -> bool:
    """Check process existence without changing its state."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main() -> int:
    """Preserve stale PID refusal, bounded TERM/KILL and terminal JSON status."""
    path = Path.home() / PROVIDER_HOME / "coderails-dashboard/dashboard.pid"
    if not path.is_file():
        print('{"status": "not_running"}')
        return 0
    try:
        pid = int(path.read_text().strip())
    except (OSError, ValueError):
        pid = 0
    command = ""
    if pid and alive(pid):
        with contextlib.suppress(OSError):
            command = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True).stdout
    if not any(token in command for token in ("npm run start", "next", "node")):
        path.unlink(missing_ok=True)
        print('{"status": "stale_pid"}')
        return 0
    with contextlib.suppress(OSError):
        os.kill(pid, signal.SIGTERM)
    for _ in range(20):
        if not alive(pid):
            break
        time.sleep(0.1)
    if alive(pid):
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)
        time.sleep(0.1)
    if alive(pid):
        print('{"status": "failed", "error": "process still running"}')
        return 1
    path.unlink(missing_ok=True)
    print('{"status": "stopped"}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
