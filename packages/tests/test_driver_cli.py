"""Both public graph CLIs run one sealed foreground driver wave."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages/graph-semantics"))
import graph_driver_process  # noqa: E402

from hooks.scripts.tests.graph_convert_test import SCRIPTS, Case  # noqa: E402
from packages.tests.test_driver_authorize import frozen_evals  # noqa: E402


class DriverCliTests(unittest.TestCase):
    """Use fake AI executables, real graph commands and real process wrappers."""

    def test_foreground_lease_refuses_second_controller_without_mutation(self) -> None:
        """A second foreground driver cannot issue a wave while the first owns it."""
        with tempfile.TemporaryDirectory() as directory:
            case = Case("codex", Path(directory))
            self.assertEqual(case.graph("convert").returncode, 0)
            self.assertEqual(case.graph("cutover-driver").returncode, 0)
            case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
            before = case.path.read_bytes()
            with graph_driver_process.lease(case.path, ".controller.lock"):
                run = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPTS["codex"]),
                        "drive",
                        str(case.path),
                        "--session",
                        "S",
                        "--checkout",
                        str(Path(directory)),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("already", run.stderr)
            self.assertEqual(case.path.read_bytes(), before)

    def test_one_wave_runs_with_both_provider_commands(self) -> None:
        """A valid terminal result records the full wave from each provider."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            checkout = base / "checkout"
            checkout.mkdir()
            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(checkout),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=t@example.test",
                    "commit",
                    "-q",
                    "--allow-empty",
                    "-m",
                    "first",
                ],
                check=True,
            )
            bindir = base / "bin"
            bindir.mkdir()
            codex = bindir / "codex"
            codex.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\nfrom pathlib import Path\n"
                "if not sys.stdin.read().startswith('CODERAILS_GRAPH_DISPATCH='): sys.exit(9)\n"
                "value = {'outcome':'done','evidence':'disposable worker'}\n"
                "Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text(json.dumps(value))\n"
                "print(json.dumps({'type':'thread.started','thread_id':'fake'}))\n"
                "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps(value)}}))\n"
                "print(json.dumps({'type':'turn.completed'}))\n"
            )
            codex.chmod(0o755)
            npx = bindir / "npx"
            npx.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "if not sys.stdin.read().startswith('CODERAILS_GRAPH_DISPATCH='): sys.exit(9)\n"
                "print(json.dumps({'type':'system','subtype':'init','session_id':'fake'}))\n"
                "print(json.dumps({'type':'result','subtype':'success','is_error':False,"
                "'structured_output':{'outcome':'done','evidence':'disposable worker'}}))\n"
            )
            npx.chmod(0o755)
            gh = bindir / "gh"
            gh.write_text("#!/bin/sh\nprintf 'disposable-token\\n'\n")
            gh.chmod(0o755)
            environment = {
                **os.environ,
                "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
                "CLAUDE_CODE_SESSION_ID": "",
            }
            for provider in ("claude", "codex"):
                case = Case(provider, base)
                state = case.read()
                state["work_units"]["1"] = {"status": "pending", "scope": "Build the disposable unit"}
                case.write(state)
                self.assertEqual(case.graph("convert").returncode, 0)
                self.assertEqual(case.graph("cutover-driver").returncode, 0)
                case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
                run = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPTS[provider]),
                        "drive",
                        str(case.path),
                        "--session",
                        "S",
                        "--checkout",
                        str(checkout),
                    ],
                    cwd=ROOT,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(run.returncode, 0, (provider, run.stderr))
                self.assertEqual(json.loads(run.stdout)["status"], "recorded")
                self.assertIsNone(case.read()["graph"]["active_wave"])


if __name__ == "__main__":
    unittest.main()
