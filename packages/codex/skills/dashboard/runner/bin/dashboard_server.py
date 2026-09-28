#!/usr/bin/env python3
"""Prepare and replace this process with the foreground provider-local dashboard server."""

import os
import re
import subprocess
import sys
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[2]
APP = DASHBOARD / "app"
PROVIDER_HOME = ".codex"
REPO = DASHBOARD.parents[3]


def validate_host(host: str) -> None:
    """Preserve the existing literal-host rule used by the request guard."""
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


def needs_build(app: Path) -> bool:
    """Rebuild missing outputs/sources or changed source, dependency and configuration files."""
    output, source = app / ".next", app / "src"
    if not output.is_dir() or not source.is_dir():
        return True
    modified = output.stat().st_mtime_ns
    if any(path.is_file() and path.stat().st_mtime_ns > modified for path in source.rglob("*")):
        return True
    return any(
        (app / name).exists() and (app / name).stat().st_mtime_ns > modified
        for name in ("package.json", "package-lock.json", "next.config.mjs")
    )


def main() -> int:
    """Heal partial installs, export builder locations, then exec npm without a PID file."""
    try:
        os.environ["PATH"] = f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        os.environ["CODERAILS_BUILDER_REPO_PATH"] = str(REPO)
        os.environ["CODERAILS_BUILDER_WRAPPER"] = str(DASHBOARD / "scripts/run_builder.py")
        os.chdir(APP)
        state = Path.home() / PROVIDER_HOME / "coderails-dashboard"
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        state.chmod(0o700)
        if not (APP / "node_modules").is_dir() or not (APP / "node_modules/.package-lock.json").is_file():
            subprocess.run(["npm", "ci"], check=True)
        if needs_build(APP):
            subprocess.run(["npm", "run", "build"], check=True)
        host = os.environ.get("DASHBOARD_HOST") or "127.0.0.1"
        validate_host(host)
        os.execvp("npm", ["npm", "run", "start", "--", "--hostname", host, "--port", "4173"])
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        return error.returncode if isinstance(error, subprocess.CalledProcessError) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
