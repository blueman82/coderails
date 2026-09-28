#!/usr/bin/env python3
"""Uninstall persistent dashboard LaunchAgents in the current user domain."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from launchd.launch_agents import run

if __name__ == "__main__":
    raise SystemExit(run("uninstall", "dashboard", Path(__file__).resolve().parent))
