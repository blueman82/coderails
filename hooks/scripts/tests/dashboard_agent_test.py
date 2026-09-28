"""Verify foreground dashboard launches and dependency/source healing without starting a server."""

import importlib
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


class DashboardAgentTests(unittest.TestCase):
    """Exercise provider-local server exports and the actual preparation decision branches."""

    def test_foreground_exec_and_healing(self) -> None:
        """Missing, partial, stale and current installations invoke the expected npm steps."""
        for prefix, home_name in (("skills.dashboard", ".claude"), ("packages.codex.skills.dashboard", ".codex")):
            module = importlib.import_module(f"{prefix}.runner.bin.dashboard_server")
            for mode in ("missing", "partial", "no-source", "stale-source", "stale-config", "current"):
                with self.subTest(prefix=prefix, mode=mode), tempfile.TemporaryDirectory() as directory:
                    base = Path(directory)
                    app = base / "app"
                    app.mkdir()
                    if mode != "missing":
                        (app / ".next").mkdir()
                        (app / "node_modules").mkdir()
                        if mode != "partial":
                            (app / "node_modules/.package-lock.json").write_text("{}")
                        if mode != "no-source":
                            (app / "src").mkdir()
                        os.utime(app / ".next", ns=(1000000000, 1000000000))
                    if mode == "stale-source":
                        (app / "src/page.ts").write_text("changed")
                    if mode == "stale-config":
                        (app / "package-lock.json").write_text("changed")
                    with (
                        patch.dict(os.environ, {"HOME": str(base), "DASHBOARD_HOST": "127.0.0.1"}),
                        patch.object(module, "APP", app),
                        patch.object(module.os, "chdir"),
                        patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run,
                        patch.object(module.os, "execvp", side_effect=SystemExit(0)) as execute,
                        self.assertRaises(SystemExit),
                    ):
                        module.main()
                    commands = [call.args[0] for call in run.call_args_list]
                    self.assertEqual(["npm", "ci"] in commands, mode in ("missing", "partial"))
                    self.assertEqual(
                        ["npm", "run", "build"] in commands,
                        mode in ("missing", "no-source", "stale-source", "stale-config"),
                    )
                    execute.assert_called_once_with(
                        "npm", ["npm", "run", "start", "--", "--hostname", "127.0.0.1", "--port", "4173"]
                    )
                    state = base / home_name / "coderails-dashboard"
                    self.assertEqual(state.stat().st_mode & 0o777, 0o700)
                    self.assertEqual(list(state.iterdir()), [])

    def test_host_rule_and_provider_builder_locations(self) -> None:
        """Reject old wildcard/hostname hazards and bind each native builder to its own tree."""
        for prefix in ("skills.dashboard", "packages.codex.skills.dashboard"):
            module = importlib.import_module(f"{prefix}.runner.bin.dashboard_server")
            for host in ("localhost", "127.0.0.1", "::1", "192.168.1.2", "2001:db8::1"):
                module.validate_host(host)
            for host in ("0.0.0.0", "::", "*", "example.com", "127.0.0.1:4173"):
                with self.assertRaises(ValueError):
                    module.validate_host(host)
            self.assertEqual(module.REPO, ROOT)
            self.assertTrue((module.DASHBOARD / "scripts/run_builder.py").is_file())
            self.assertTrue(module.APP.is_dir())
            self.assertIn("start", json.loads((module.APP / "package.json").read_text())["scripts"])

    def test_launchd_plist_contract(self) -> None:
        """Preserve foreground KeepAlive scheduling, bounded retries and persistent log paths."""
        path = ROOT / "launchd/com.coderails.dashboard.plist"
        value = plistlib.loads(path.read_bytes())
        self.assertEqual(value["Label"], "com.coderails.dashboard")
        self.assertTrue(value["RunAtLoad"])
        self.assertTrue(value["KeepAlive"])
        self.assertEqual(value["ThrottleInterval"], 60)
        self.assertTrue(value["ProgramArguments"][0].endswith("skills/dashboard/runner/bin/dashboard_server.py"))
        for name in ("StandardOutPath", "StandardErrorPath"):
            self.assertTrue(value[name].endswith("coderails-dashboard/dashboard.log"))


if __name__ == "__main__":
    unittest.main()
