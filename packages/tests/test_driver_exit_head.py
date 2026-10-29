"""Paused publication keeps the worker-exit HEAD separate from the published HEAD."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from hooks.scripts.tests.graph_convert_test import SCRIPTS, Case  # noqa: E402
from packages.tests import test_driver_paths as path_tests  # noqa: E402


class DriverExitHeadTests(unittest.TestCase):
    """Use real wrappers and graph consumers with synthetic Codex and GitHub processes."""

    @staticmethod
    def setup_worker(base: Path) -> tuple[Case, Path, dict[str, str], list[str], str]:
        """Leave one successful synthetic child waiting before it exits."""
        case, checkout, _ = path_tests.DriverPathTests.setup_case(base)
        tools = base / "bin"
        tools.mkdir()
        worker = tools / "codex"
        worker.write_text(
            "#!/usr/bin/env python3\nimport json, sys, time\nfrom pathlib import Path\n"
            f"release = Path({str(base / 'release')!r})\n"
            "sys.stdin.buffer.read()\n"
            "while not release.exists(): time.sleep(0.01)\n"
            "result = {'outcome':'done','evidence':'synthetic source-only result','final_report': "
            "{'claims':[{'text':'Synthetic child finished','label':'verified','source':'synthetic child'}],"
            "'did_not_verify':[]}}\n"
            "Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text(json.dumps(result))\n"
            "print(json.dumps({'type':'thread.started','thread_id':'synthetic-exit-head'}))\n"
            "print(json.dumps({'type':'item.completed',"
            "'item':{'type':'agent_message','text':json.dumps(result)}}))\n"
            "print(json.dumps({'type':'turn.completed'}))\n"
        )
        worker.chmod(0o755)
        gh = tools / "gh"
        gh.write_text(
            "#!/usr/bin/env python3\nimport json, subprocess, sys\nfrom pathlib import Path\n"
            f"if not Path({str(base / 'published')!r}).exists(): raise SystemExit(1)\n"
            "head = subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()\n"
            "print(json.dumps({'number':42,'state':'OPEN','headRefOid':head}))\n"
        )
        gh.chmod(0o755)
        environment = {"PATH": f"{tools}:{os.environ['PATH']}", "HOME": str(base), "CODEX_HOME": str(base)}
        command = [
            sys.executable,
            str(SCRIPTS["codex"]),
            "drive",
            str(case.path),
            "--session",
            "S",
            "--checkout",
            str(checkout),
            "--wait-seconds",
            "0",
        ]
        head = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
        run = subprocess.run(command, env=environment, capture_output=True, text=True, check=False)
        if run.returncode or json.loads(run.stdout)["status"] != "running":
            raise AssertionError((run.stdout, run.stderr))
        return case, checkout, environment, command, head

    def finish_worker(self, base: Path, case: Case) -> Path:
        """Wait for the existing wrapper's atomic terminal publication."""
        (base / "release").touch()
        artifact = next(case.path.parent.glob("driver-evidence/*"))
        for _ in range(500):
            if (artifact / "terminal.json").is_file():
                return artifact
            time.sleep(0.01)
        self.fail((artifact / "stderr.log").read_text())

    def test_receipt_preserves_exit_head_before_first_observation_and_publication(self) -> None:
        """A root commit after terminal output cannot replace the worker-exit provenance."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            case, checkout, env, command, exit_head = self.setup_worker(base)
            artifact = self.finish_worker(base, case)
            terminal = json.loads((artifact / "terminal.json").read_text())
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(checkout),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.test",
                    "commit",
                    "-q",
                    "--allow-empty",
                    "-m",
                    "synthetic root publication",
                ],
                check=True,
            )
            published_head = subprocess.check_output(
                ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
            ).strip()
            self.assertNotEqual(exit_head, published_head)
            pause = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
            self.assertEqual(pause.returncode, 0, pause.stderr)
            self.assertEqual(json.loads(pause.stdout)["reason"], "publication_required")
            pending = artifact / "prepublication.json"
            self.assertEqual(json.loads(pending.read_text())["head_at_exit"], exit_head)
            self.assertEqual(terminal.get("head_at_exit"), exit_head)
            original = pending.read_bytes()
            again = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(pending.read_bytes(), original)
            pending.write_bytes(original + b" ")
            (base / "published").touch()
            recorded = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
            self.assertEqual(json.loads(recorded.stdout)["status"], "recorded")
            manifest = json.loads((artifact / "manifest.json").read_text())
            self.assertEqual(manifest["head"], published_head)
            self.assertEqual(json.loads(pending.read_text())["head_at_exit"], exit_head)
            self.assertEqual(len(list(case.path.parent.glob("driver-evidence/*"))), 1)
            pending.write_bytes(pending.read_bytes() + b" ")
            refused = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("prepublication evidence changed", refused.stderr)

    def test_changed_exit_head_or_missing_receipt_provenance_refuses_before_manifest(self) -> None:
        """A valid-looking forged head and an unqualified old receipt cannot release the attempt."""
        for mode in ("changed_seal", "missing_receipt_head", "malformed_receipt_head"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                case, _, env, command, _ = self.setup_worker(base)
                artifact = self.finish_worker(base, case)
                pause = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
                self.assertEqual(pause.returncode, 0, pause.stderr)
                pending = artifact / "prepublication.json"
                receipt_path = artifact / "terminal.json"
                original_seal, original_receipt = pending.read_bytes(), receipt_path.read_bytes()
                if mode == "changed_seal":
                    saved = json.loads(original_seal)
                    saved["head_at_exit"] = "f" * 40
                    pending.write_text(json.dumps(saved))
                else:
                    receipt = json.loads(original_receipt)
                    receipt.pop("head_at_exit", None)
                    if mode == "malformed_receipt_head":
                        receipt["head_at_exit"] = "not-a-commit"
                    receipt_path.write_text(json.dumps(receipt))
                before = case.path.read_bytes()
                refused = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
                self.assertNotEqual(refused.returncode, 0, refused.stdout)
                self.assertIn("exit HEAD", refused.stderr)
                self.assertEqual(case.path.read_bytes(), before)
                self.assertFalse((artifact / "manifest.json").exists())
                pending.write_bytes(original_seal)
                receipt_path.write_bytes(original_receipt)
                (base / "published").touch()
                accepted = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
                self.assertEqual(accepted.returncode, 0, accepted.stderr)
                self.assertEqual(json.loads(accepted.stdout)["status"], "recorded")


if __name__ == "__main__":
    unittest.main()
