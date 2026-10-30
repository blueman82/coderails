"""Driver CLI paths retain their meaning when the child uses another working directory."""

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
from hooks.scripts.tests.graph_convert_test import SCRIPTS, Case  # noqa: E402
from packages.tests import test_driver_controller as controller_tests  # noqa: E402
from packages.tests.test_driver_authorize import frozen_evals  # noqa: E402


class DriverPathTests(unittest.TestCase):
    """Run real graph commands and a synthetic Codex child from a separate checkout."""

    @staticmethod
    def setup_case(base: Path, guarded: bool = False) -> tuple[Case, Path, str]:
        """Create one narrow dispatch and a real disposable source HEAD."""
        case = Case("codex", base)
        controller_tests.DriverControllerTests.scoped(case)
        node = "S2" if guarded else "U3[1]"
        if guarded:
            state = case.read()
            state["graph"]["nodes"][node] = state["graph"]["nodes"].pop("U3[1]")
            state["graph"]["nodes"][node]["label"] = "Run preflight"
            case.write(state)
        for name in ("convert", "cutover-driver"):
            run = case.graph(name)
            if run.returncode:
                raise AssertionError(run.stderr)
        case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
        checkout = base / "checkout"
        controller_tests.DriverControllerTests.checkout(checkout)
        return case, checkout, node

    def test_relative_and_absolute_drive_record_child_failure_without_orphaning_attempt(self) -> None:
        """Both route types finish a synthetic failed result and keep its terminal evidence."""
        for relative in (False, True):
            for guarded in (False, True):
                with self.subTest(relative=relative, guarded=guarded), tempfile.TemporaryDirectory() as directory:
                    base = Path(directory)
                    case, checkout, node = self.setup_case(base, guarded)
                    tools = base / "bin"
                    tools.mkdir()
                    capture = base / "child.json"
                    child = tools / "codex"
                    child.write_text(
                        "#!/usr/bin/env python3\nimport hashlib, json, os, sys\nfrom pathlib import Path\n"
                        "prompt = sys.stdin.buffer.read()\n"
                        "assert prompt.startswith(b'CODERAILS_GRAPH_DISPATCH=')\n"
                        "schema = sys.argv[sys.argv.index('--output-schema') + 1]\n"
                        "final = sys.argv[sys.argv.index('--output-last-message') + 1]\n"
                        f"Path({str(capture)!r}).write_text(json.dumps(\n"
                        "    {'cwd': os.getcwd(), 'schema': schema, 'final': final,\n"
                        "     'digest': hashlib.sha256(prompt).hexdigest()}))\n"
                        "result = {'outcome':'failed', 'evidence':'synthetic source-only child failure', "
                        "'final_report':None}\n"
                        "Path(final).write_text(json.dumps(result))\n"
                        "print(json.dumps({'type':'thread.started', 'thread_id':'synthetic-path-test'}))\n"
                        "print(json.dumps({'type':'item.completed', "
                        "'item':{'type':'agent_message', 'text':json.dumps(result)}}))\n"
                        "print(json.dumps({'type':'turn.completed'}))\n"
                    )
                    child.chmod(0o755)
                    state_path = case.path.relative_to(base) if relative else case.path
                    checkout_arg = checkout.relative_to(base) if relative else checkout
                    run = subprocess.run(
                        [
                            sys.executable,
                            str(SCRIPTS["codex"]),
                            "drive",
                            str(state_path),
                            "--session",
                            "S",
                            "--checkout",
                            str(checkout_arg),
                            "--wait-seconds",
                            "3",
                        ],
                        cwd=base,
                        env={"PATH": f"{tools}:{os.environ['PATH']}", "HOME": directory, "CODEX_HOME": directory},
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=15,
                    )
                    self.assertEqual(run.returncode, 0, run.stderr)
                    self.assertEqual(json.loads(run.stdout)["status"], "recorded", run.stdout)
                    state = case.read()
                    self.assertIsNone(state["graph"]["active_wave"])
                    self.assertEqual(state["graph"]["nodes"][node]["retry"]["attempts"], 1)
                    seen = json.loads(capture.read_text())
                    self.assertEqual(Path(seen["cwd"]).resolve(), checkout.resolve())
                    self.assertTrue(Path(seen["schema"]).is_absolute())
                    self.assertTrue(Path(seen["final"]).is_absolute())
                    artifacts = list(case.path.parent.glob("driver-evidence/*"))
                    self.assertEqual(len(artifacts), 1)
                    self.assertEqual(json.loads((artifacts[0] / "launch.json").read_text())["status"], "started")
                    self.assertEqual(json.loads((artifacts[0] / "terminal.json").read_text())["exit_code"], 0)
                    self.assertNotIn("Traceback", (artifacts[0] / "stderr.log").read_text())
                    self.assertFalse(list(artifacts[0].glob("*.tmp")))

    def test_relative_missing_checkout_refuses_before_authorization_or_reservation(self) -> None:
        """Invalid input leaves the pending graph and process attempts untouched."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            case, _, _ = self.setup_case(base)
            before = case.path.read_bytes()
            run = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS["codex"]),
                    "drive",
                    str(case.path.relative_to(base)),
                    "--session",
                    "S",
                    "--checkout",
                    "missing",
                ],
                cwd=base,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("worker checkout is missing", run.stderr)
            self.assertEqual(case.path.read_bytes(), before)
            self.assertFalse(case.read()["graph"]["dispatches"])
            self.assertFalse(list(base.rglob("launch.json")))


if __name__ == "__main__":
    unittest.main()
