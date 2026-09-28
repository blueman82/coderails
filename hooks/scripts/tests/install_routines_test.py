#!/usr/bin/env python3
"""Verify persistent LaunchAgent installation in a private HOME with inert native process stubs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.hook_test_support import ROOT, HookTestCase
from launchd.launch_agents import uninstall_agent


class LaunchAgentTests(HookTestCase):
    """Install copies, idempotency, empty globs, and teardown refusal preserve user state."""

    def setUp(self) -> None:
        """Provide inert launchctl/lsof executables and an isolated home for every case."""
        super().setUp()
        self.home = self.directory / "home"
        self.home.mkdir()
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.log = self.directory / "launchctl.jsonl"
        stub = self.bin / "launchctl"
        stub.write_text(
            f"#!{sys.executable}\nimport json,os,sys\n"
            'with open(os.environ["LAUNCHCTL_LOG"],"a") as f:\n'
            ' f.write(json.dumps(sys.argv[1:])+"\\n")\n'
            'raise SystemExit(1 if sys.argv[1]=="print" else 0)\n'
        )
        stub.chmod(0o755)
        listener = self.bin / "lsof"
        listener.write_text(f"#!{sys.executable}\nraise SystemExit(1)\n")
        listener.chmod(0o755)
        self.environment.update(
            PYTHONDONTWRITEBYTECODE="1",
            HOME=str(self.home),
            PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
            LAUNCHCTL_LOG=str(self.log),
        )

    def launch(
        self, operation: str, kind: str = "routines", directory: Path = ROOT / "launchd"
    ) -> subprocess.CompletedProcess[str]:
        """Invoke the actual native installer or uninstaller entry point."""
        return subprocess.run(
            [sys.executable, str(directory / f"{operation}_{kind}.py")],
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_routine_install_uninstall_idempotence_and_legacy_absence(self) -> None:
        """Both routine plists bootstrap from persistent byte-identical copies, then unload by label."""
        for _ in range(2):
            result = self.launch("install")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        destination = self.home / "Library/LaunchAgents"
        labels = ["com.coderails.routine-sweeper.calendar", "com.coderails.routine-sweeper.watch"]
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(len(list(destination.glob("*.plist"))), 2)
        for label in labels:
            copied = destination / f"{label}.plist"
            self.assertEqual(copied.read_bytes(), (ROOT / "launchd" / copied.name).read_bytes())
            self.assertIn(["bootstrap", f"gui/{os.getuid()}", str(copied)], calls)
            self.assertNotIn(["bootstrap", f"gui/{os.getuid()}", str(ROOT / "launchd" / copied.name)], calls)
        self.assertEqual((self.home / ".claude/coderails-dashboard/routines").stat().st_mode & 0o777, 0o700)
        for _ in range(3):
            result = self.launch("uninstall")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(list(destination.glob("*.plist")))
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        for label in labels:
            self.assertIn(["bootout", f"gui/{os.getuid()}/{label}"], calls)

    def test_empty_glob_refuses_without_mutation(self) -> None:
        """A release directory without plists refuses before creating any user files or invoking launchctl."""
        directory = self.directory / "launchd"
        directory.mkdir()
        for name in ("install_routines.py", "uninstall_routines.py", "launch_agents.py"):
            shutil.copyfile(ROOT / "launchd" / name, directory / name)
        for operation in ("install", "uninstall"):
            result = self.launch(operation, directory=directory)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no com.coderails.routine-sweeper", result.stderr)
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertFalse(self.log.exists())

    def test_dashboard_agent_copy_and_async_bootout_refusal(self) -> None:
        """Dashboard persistence mirrors routines, and a still-loaded job retains its plist."""
        logs = self.home / ".claude/coderails-dashboard"
        logs.mkdir(parents=True, mode=0o755)
        result = self.launch("install", "dashboard_agent")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(logs.stat().st_mode & 0o777, 0o700)
        destination = self.home / "Library/LaunchAgents/com.coderails.dashboard.plist"
        self.assertEqual(destination.read_bytes(), (ROOT / "launchd/com.coderails.dashboard.plist").read_bytes())
        self.assertEqual(destination.stat().st_mode & 0o777, 0o644)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(
            calls,
            [
                ["bootout", f"gui/{os.getuid()}/com.coderails.dashboard"],
                ["bootstrap", f"gui/{os.getuid()}", str(destination)],
            ],
        )

        with (
            patch("launchd.launch_agents.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")),
            patch("launchd.launch_agents.time.sleep"),
            self.assertRaisesRegex(ValueError, "still loaded"),
        ):
            uninstall_agent("com.coderails.dashboard", self.home, wait=True)
        self.assertTrue(destination.exists())
        for _ in range(2):
            result = self.launch("uninstall", "dashboard_agent")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
