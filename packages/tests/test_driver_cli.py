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
import graph_driver_control  # noqa: E402
import graph_driver_process  # noqa: E402

from hooks.scripts.tests.graph_convert_test import SCRIPTS, Case  # noqa: E402
from packages.tests.test_driver_authorize import frozen_evals  # noqa: E402


class DriverCliTests(unittest.TestCase):
    """Use fake AI executables, real graph commands and real process wrappers."""

    def test_assign_pending_unit_scope_requires_quiet_graph(self) -> None:
        """An existing unit can gain a task only before its next wave."""
        with tempfile.TemporaryDirectory() as directory:
            for provider in ("claude", "codex"):
                case = Case(provider, Path(directory))
                self.assertEqual(case.graph("convert").returncode, 0)
                command = ("assign-unit-scope", "--session", "S", "--unit", "1", "--scope", "Build unit one")
                state = case.read()
                state["work_units"]["1"] = {"status": "pending"}
                case.write(state)
                before = case.path.read_bytes()
                state["graph"]["active_wave"] = {"wave_id": "wave-2", "revision": 2, "nodes": ["U3[1]"]}
                case.write(state)
                busy = case.graph(*command)
                self.assertNotEqual(busy.returncode, 0, (provider, busy.stdout))
                self.assertEqual(case.read()["work_units"]["1"], {"status": "pending"})
                case.path.write_bytes(before)
                assigned = case.graph(*command)
                self.assertEqual(assigned.returncode, 0, (provider, assigned.stderr))
                self.assertEqual(case.read()["work_units"]["1"]["scope"], "Build unit one")
                self.assertNotEqual(case.graph(*command).returncode, 0)

    def test_root_control_result_is_sealed_and_revalidated(self) -> None:
        """A root proof step completes through an owned result file, without a worker."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for provider in ("claude", "codex"):
                case = Case(provider, base)
                state = case.read()
                state["graph"]["nodes"]["S13-proof"] = state["graph"]["nodes"].pop("U3[1]")
                state["graph"]["nodes"]["S13-proof"]["label"] = "Run frozen proofs"
                case.write(state)
                self.assertEqual(case.graph("convert").returncode, 0)
                self.assertEqual(case.graph("cutover-driver").returncode, 0)
                case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
                drive = [sys.executable, str(SCRIPTS[provider]), "drive", str(case.path), "--session", "S"]
                opened = subprocess.run(drive, capture_output=True, text=True, check=False)
                self.assertEqual(opened.returncode, 0, (provider, opened.stderr))
                self.assertEqual(json.loads(opened.stdout)["reason"], "control_node")
                active = case.read()["graph"]["active_wave"]
                self.assertEqual(active["nodes"], ["S13-proof"])
                self.assertFalse(case.read()["graph"]["dispatches"])
                result_file = base / f"{provider}-proof-result.json"
                original = json.dumps({"outcome": "done", "evidence": "disposable root proof"})
                result_file.write_text(original)
                staged = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPTS[provider]),
                        "record-driver-control",
                        str(case.path),
                        "--session",
                        "S",
                        "--node",
                        "S13-proof",
                        "--result-file",
                        str(result_file),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(staged.returncode, 0, (provider, staged.stderr))
                foreign = case.read()
                foreign["graph"]["active_wave"]["wave_id"] = "wave-999"
                with self.assertRaisesRegex(ValueError, "another wave"):
                    graph_driver_control.validate(case.path, foreign, "S13-proof", json.loads(staged.stdout))
                before = case.path.read_bytes()
                result_file.write_text(original + " ")
                denied = subprocess.run(drive, capture_output=True, text=True, check=False)
                self.assertNotEqual(denied.returncode, 0, (provider, denied.stdout, denied.stderr))
                self.assertEqual(case.path.read_bytes(), before)
                result_file.write_text(original)
                recorded = subprocess.run(drive, capture_output=True, text=True, check=False)
                self.assertEqual(recorded.returncode, 0, (provider, recorded.stderr))
                self.assertEqual(json.loads(recorded.stdout)["status"], "recorded")
                node = case.read()["graph"]["nodes"]["S13-proof"]
                self.assertEqual(node["status"], "done")
                self.assertEqual(node["evidence"][-1]["kind"], "root_control")
                recorded_bytes = case.path.read_bytes()
                result_file.write_text(original + " ")
                stale = subprocess.run(drive, capture_output=True, text=True, check=False)
                self.assertNotEqual(stale.returncode, 0, (provider, stale.stdout, stale.stderr))
                self.assertEqual(case.path.read_bytes(), recorded_bytes)
                result_file.write_text(original)

    def test_checkout_map_option_refuses_wrong_node_without_mutation(self) -> None:
        """Both public CLIs parse the map and bind it to the full ready set."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            mapping = base / "checkouts.json"
            mapping.write_text(json.dumps({"U3[2]": str(base)}))
            for provider in ("claude", "codex"):
                case = Case(provider, base)
                state = case.read()
                state["work_units"]["1"] = {"status": "pending", "scope": "Build the disposable unit"}
                case.write(state)
                self.assertEqual(case.graph("convert").returncode, 0)
                self.assertEqual(case.graph("cutover-driver").returncode, 0)
                case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
                before = case.path.read_bytes()
                run = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPTS[provider]),
                        "drive",
                        str(case.path),
                        "--session",
                        "S",
                        "--checkout-map",
                        str(mapping),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(run.returncode, 0, (provider, run.stderr))
                self.assertEqual(json.loads(run.stdout)["reason"], "checkout_map_mismatch")
                self.assertEqual(case.path.read_bytes(), before)

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
                "value = {'outcome':'done','evidence':'disposable worker','final_report':"
                "{'claims':[{'text':'Disposable result','label':'verified','source':'scratch checkout'}],"
                "'did_not_verify':[]}}\n"
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
                "'structured_output':{'outcome':'done','evidence':'disposable worker','final_report':"
                "{'claims':[{'text':'Disposable result','label':'verified','source':'scratch checkout'}],"
                "'did_not_verify':[]}}}))\n"
            )
            npx.chmod(0o755)
            gh = bindir / "gh"
            head = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
            response = json.dumps({"number": 42, "state": "OPEN", "headRefOid": head})
            gh.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = auth ]; then printf 'disposable-token\\n'; "
                "else printf '%s\\n' '" + response + "'; fi\n"
            )
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
                self.assertEqual(case.read()["final_reports"]["U3[1]"]["claims"][0]["source"], "scratch checkout")


if __name__ == "__main__":
    unittest.main()
