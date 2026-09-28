"""Persistent user LaunchAgent operations without invoking a shell."""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def routine_plists(directory: Path) -> list[Path]:
    """Require at least one routine-specific plist before changing launchd."""
    plists = sorted(directory.glob("com.coderails.routine-sweeper.*.plist"))
    if not plists:
        raise ValueError(f"no com.coderails.routine-sweeper.*.plist found in {directory}")
    return plists


def install_agent(source: Path, home: Path) -> None:
    """Copy a plist into the persistent location before bootstrapping it."""
    destination = home / "Library/LaunchAgents" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"Installing: {source.stem} ({source})")
    shutil.copyfile(source, destination)
    destination.chmod(0o644)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{source.stem}"], stderr=subprocess.DEVNULL, check=False)
    subprocess.run(["launchctl", "bootstrap", domain, str(destination)], check=True)
    print(f"Installed: {source.stem}")


def uninstall_agent(label: str, home: Path, *, wait: bool = False) -> None:
    """Unload by label and retain a dashboard copy if asynchronous teardown fails."""
    target = f"gui/{os.getuid()}/{label}"
    destination = home / "Library/LaunchAgents" / f"{label}.plist"
    result = subprocess.run(
        ["launchctl", "bootout", target], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False
    )
    if wait:
        for _ in range(10):
            status = subprocess.run(
                ["launchctl", "print", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
            )
            if status.returncode:
                break
            time.sleep(1)
        else:
            detail = f"\nbootout said: {result.stderr}" if result.stderr else ""
            raise ValueError(
                f"{label} is still loaded after bootout{detail}\n"
                f"Leaving {destination} in place (job still loaded, not safe to remove)"
            )
    destination.unlink(missing_ok=True)
    print(f"Uninstalled (or was already absent): {label}")


def require_dashboard_port() -> None:
    """Reject a live listener before creating a dashboard crash loop."""
    try:
        result = subprocess.run(
            ["lsof", "-nP", "-iTCP:4173", "-sTCP:LISTEN"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return
    if result.returncode == 0 and result.stdout.strip():
        raise ValueError(
            "Port 4173 is already in use by another process:\n"
            + result.stdout
            + "Stop the manually-started dashboard first (python3 skills/dashboard/scripts/stop_dashboard.py), "
            "or the agent will crash-loop every 60s on EADDRINUSE."
        )


def run(operation: str, kind: str, directory: Path) -> int:
    """Perform the selected user-agent operation with legacy failure statuses."""
    home = Path.home()
    try:
        sources = routine_plists(directory) if kind == "routines" else [directory / "com.coderails.dashboard.plist"]
        if operation == "install":
            log = home / ".claude/coderails-dashboard"
            if kind == "routines":
                log /= "routines"
            log.mkdir(parents=True, mode=0o700, exist_ok=True)
            if kind == "dashboard":
                log.chmod(0o700)
                require_dashboard_port()
            for source in sources:
                install_agent(source, home)
        else:
            for source in sources:
                uninstall_agent(source.stem, home, wait=kind == "dashboard")
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
