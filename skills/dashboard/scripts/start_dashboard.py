#!/usr/bin/env python3
"""Start the production dashboard in a detached process and open its validated URL."""

import contextlib
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
PROVIDER_HOME = ".claude"


def alive(pid: int) -> bool:
    """Probe liveness without signalling a process to terminate."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def dashboard_pid(pid: int) -> bool:
    """Retain the original command-line identity guard against PID reuse."""
    try:
        result = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
        return any(token in result.stdout for token in ("npm run start", "next", "node"))
    except OSError:
        return False


def read_pid(path: Path) -> int:
    """Missing, empty and malformed PID files describe no owned process."""
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return 0


def stop_previous(path: Path) -> None:
    """Stop only an identified previous instance, then remove its stale PID file."""
    if not path.is_file():
        return
    pid = read_pid(path)
    if pid and alive(pid) and dashboard_pid(pid):
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if not alive(pid):
                break
            time.sleep(0.1)
    path.unlink(missing_ok=True)


def validate_host(host: str) -> None:
    """Preserve literal-host acceptance including historical bare-colon IPv6 handling."""
    accepted = host in ("localhost", "127.0.0.1", "::1") or (
        host not in ("0.0.0.0", "::", "*")
        and not re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}:[0-9]+", host)
        and (re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", host) is not None or ":" in host)
    )
    if not accepted:
        raise ValueError(
            f"DASHBOARD_HOST='{host}' is not a concrete host IP (wildcards like 0.0.0.0 "
            "and host:port forms are rejected — the guard exact-matches one host; see SKILL.md)"
        )


def prepare_app() -> None:
    """Interactive start installs missing dependencies and rebuilds changed source only."""
    if not (APP / "node_modules").is_dir():
        print("Installing dependencies (npm ci)...", flush=True)
        subprocess.run(["npm", "ci"], check=True)
    output = APP / ".next"
    rebuild = not output.is_dir()
    if not rebuild:
        modified = output.stat().st_mtime_ns
        rebuild = any(path.is_file() and path.stat().st_mtime_ns > modified for path in (APP / "src").rglob("*"))
    if rebuild:
        print("Building dashboard (npm run build)...", flush=True)
        subprocess.run(["npm", "run", "build"], check=True)


def await_ready(child: subprocess.Popen[bytes], url: str, pid_file: Path, log: Path) -> None:
    """Require a live owned child both before probing and after readiness succeeds."""
    for _ in range(50):
        if child.poll() is not None:
            pid_file.unlink(missing_ok=True)
            raise ValueError(f"Dashboard server exited early. See {log}")
        try:
            result = subprocess.run(["curl", "-s", "-o", os.devnull, url], stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                break
        except OSError:
            pass
        time.sleep(0.2)
    else:
        raise ValueError(f"Dashboard did not become ready within 10s. See {log}")
    if child.poll() is not None:
        pid_file.unlink(missing_ok=True)
        raise ValueError(f"Dashboard server exited after reporting ready. See {log}")


def main() -> int:
    """Keep failure diagnostics, state paths, process detachment and readiness ownership."""
    try:
        host, port = os.environ.get("DASHBOARD_HOST") or "127.0.0.1", os.environ.get("DASHBOARD_PORT") or "4173"
        validate_host(host)
        state = Path.home() / PROVIDER_HOME / "coderails-dashboard"
        state.mkdir(parents=True, exist_ok=True)
        pid_file, log = state / "dashboard.pid", state / "dashboard.log"
        os.chdir(APP)
        prepare_app()
        stop_previous(pid_file)
        with contextlib.suppress(FileNotFoundError):
            holder = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True)
            if holder.returncode == 0 and holder.stdout.strip():
                raise ValueError(f"Port {port} is already in use by another process:\n{holder.stdout.rstrip()}")
        with log.open("wb") as stream:
            child = subprocess.Popen(
                ["nohup", "npm", "run", "start", "--", "--hostname", host, "--port", port],
                stdout=stream,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        pid_file.write_text(f"{child.pid}\n")
        url = f"http://{host}:{port}"
        await_ready(child, url, pid_file, log)
        print(f"Dashboard running at {url} (pid {child.pid})")
        with contextlib.suppress(OSError):
            subprocess.run(["open", url], stderr=subprocess.DEVNULL)
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        return error.returncode if isinstance(error, subprocess.CalledProcessError) else 1


if __name__ == "__main__":
    raise SystemExit(main())
