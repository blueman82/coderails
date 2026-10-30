"""Public driver resume rechecks an authorized dispatch before launching its worker."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills/agentic-loop/scripts"))
import graph_driver_dispatch  # noqa: E402
import graph_driver_evidence  # noqa: E402

from hooks.scripts.tests.graph_convert_test import SCRIPTS, Case  # noqa: E402
from packages.tests import test_driver_controller as controller_tests  # noqa: E402
from packages.tests.test_driver_authorize import frozen_evals  # noqa: E402


def prepare_authorized(test: unittest.TestCase, base: Path, node_id: str) -> tuple[Case, Path, str, Path]:
    """Authorize a real dispatch, leaving its process unstarted as after a controller crash."""
    case = Case("codex", base)
    controller_tests.DriverControllerTests.scoped(case)
    state = case.read()
    state["graph"]["nodes"][node_id] = state["graph"]["nodes"].pop("U3[1]")
    if node_id == "S2":
        state["graph"]["nodes"][node_id]["label"] = "Run preflight"
    case.write(state)
    converted = case.graph("convert")
    test.assertEqual(converted.returncode, 0, converted.stderr)
    test.assertEqual(case.graph("cutover-driver").returncode, 0)
    case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
    checkout = base / "checkout"
    controller_tests.DriverControllerTests.checkout(checkout)
    opened = subprocess.run(
        [sys.executable, str(SCRIPTS["codex"]), "begin-driver-wave", str(case.path)],
        capture_output=True,
        text=True,
        check=False,
    )
    test.assertEqual(opened.returncode, 0, opened.stderr)
    identifier = json.loads(opened.stdout)["dispatches"][0]["dispatch_id"]
    record = case.read()["graph"]["dispatches"][identifier]
    prompt = graph_driver_dispatch.write_prompt(
        case.path, case.read(), identifier, record, checkout.resolve(), "codex", SCRIPTS["codex"]
    )
    authorized = case.graph(
        "authorize-driver",
        "--dispatch-id",
        identifier,
        "--prompt-file",
        str(prompt),
        "--role",
        record["contract"]["role"],
        "--driver-run-id",
        "owned-resume",
    )
    test.assertEqual(authorized.returncode, 0, authorized.stderr)
    return case, checkout, identifier, prompt


class DriverResumeTests(unittest.TestCase):
    """Use owned graph commands and a disposable CLI that only captures stdin and emits JSON."""

    def drive(
        self, case: Case, checkout: Path, base: Path, *, malformed: bool = False
    ) -> subprocess.CompletedProcess[str]:
        """Run the public consumer through a private synthetic Codex executable."""
        tools = base / "bin"
        tools.mkdir()
        cli = tools / "codex"
        cli.write_text(
            f"#!{sys.executable}\nimport json, sys\nfrom pathlib import Path\n"
            f"Path({str(base / 'stdin.bin')!r}).write_bytes(sys.stdin.buffer.read())\n"
            f"result = {{'outcome': {([] if malformed else 'failed')!r}, "
            "'evidence': 'inert result', 'final_report': None}\n"
            "Path(sys.argv[sys.argv.index('--output-last-message') + 1]).write_text(json.dumps(result))\n"
            "print(json.dumps({'type': 'thread.started', 'thread_id': 'inert-thread'}))\n"
            "print(json.dumps({'type': 'item.completed', "
            "'item': {'type': 'agent_message', 'text': json.dumps(result)}}))\n"
            "print(json.dumps({'type': 'turn.completed'}))\n"
        )
        cli.chmod(0o755)
        home = base / "home"
        home.mkdir()
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPTS["codex"]),
                "drive",
                str(case.path),
                "--session",
                "S",
                "--checkout",
                str(checkout),
            ],
            env={"PATH": f"{tools}:{os.environ['PATH']}", "HOME": str(home), "CODEX_HOME": str(home)},
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def test_owned_authorized_resume_delivers_checked_stdin_and_records_failure(self) -> None:
        """Both ordinary and guarded workers resume the original authorization without replacing it."""
        for node_id in ("U3[1]", "S2"):
            with self.subTest(node=node_id), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                case, checkout, identifier, prompt = prepare_authorized(self, base, node_id)
                authorization = case.read()["graph"]["dispatches"][identifier]["authorized"]
                result = self.drive(case, checkout, base)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["status"], "recorded")
                self.assertEqual((base / "stdin.bin").read_bytes(), prompt.read_bytes())
                state = case.read()
                self.assertEqual(state["graph"]["dispatches"][identifier]["authorized"], authorization)
                self.assertEqual(state["graph"]["nodes"][node_id]["retry"]["attempts"], 1)

    def test_resume_refuses_changed_record_or_live_attempt_before_worker_input(self) -> None:
        """A retained authorization cannot start an ordinary or guarded worker under another attempt."""
        for node_id in ("U3[1]", "S2"):
            for change in ("record", "node"):
                with self.subTest(node=node_id, change=change), tempfile.TemporaryDirectory() as directory:
                    base = Path(directory)
                    case, checkout, identifier, prompt = prepare_authorized(self, base, node_id)
                    state = case.read()
                    if change == "record":
                        state["graph"]["dispatches"][identifier]["attempt"] = 2
                    else:
                        state["graph"]["nodes"][node_id]["retry"]["attempts"] = 1
                    case.write(state)
                    before = case.path.read_bytes()
                    result = self.drive(case, checkout, base)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn("attempt", result.stderr)
                    self.assertEqual(case.path.read_bytes(), before)
                    self.assertFalse((base / "stdin.bin").exists())
                    self.assertFalse((prompt.parent / "launch.json").exists())

    def test_malformed_finished_result_records_a_failed_attempt(self) -> None:
        """Untrusted output types reach normal failure accounting instead of escaping the consumer."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            case, checkout, _identifier, _prompt = prepare_authorized(self, base, "S2")
            result = self.drive(case, checkout, base, malformed=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "recorded")
            self.assertEqual(case.read()["graph"]["nodes"]["S2"]["retry"]["attempts"], 1)

    def test_failed_history_survives_a_later_active_wave(self) -> None:
        """The public consumer can revalidate a closed failed attempt while its retry wave is active."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            case, checkout, identifier, prompt = prepare_authorized(self, base, "S2")
            first = self.drive(case, checkout, base)
            self.assertEqual(first.returncode, 0, first.stderr)
            manifest = (prompt.parent / "manifest.json").read_bytes()
            later = base / "later"
            later.mkdir()
            next_checkout = later / "checkout"
            controller_tests.DriverControllerTests.checkout(next_checkout)
            second = self.drive(case, next_checkout, later)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(json.loads(second.stdout)["status"], "recorded")
            state = case.read()
            self.assertEqual(state["graph"]["nodes"]["S2"]["retry"]["attempts"], 2)
            references = [
                cast(dict[str, Any], item)
                for item in state["graph"]["nodes"]["S2"]["evidence"]
                if isinstance(item, dict) and cast(dict[str, Any], item).get("kind") == "driver_worker"
            ]
            self.assertEqual(len(references), 2)
            self.assertEqual((prompt.parent / "manifest.json").read_bytes(), manifest)
            self.assertIn(identifier, state["graph"]["dispatches"])

    def test_evidence_admission_rechecks_live_attempt_and_preserves_history(self) -> None:
        """An old manifest remains readable as history but cannot be admitted as the next live attempt."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            case, checkout, identifier, prompt = prepare_authorized(self, base, "S2")
            parsed = {"outcome": "failed", "evidence": "inert failed result", "final_report": None}
            (prompt.parent / "output.jsonl").write_text("inert output\n")
            (prompt.parent / "final.json").write_text(json.dumps(parsed))
            reference = graph_driver_evidence.seal(
                case.path, case.read(), "S2", identifier, checkout, "codex", 0, parsed
            )
            state = case.read()
            state["graph"]["nodes"]["S2"]["retry"]["attempts"] = 1
            self.assertEqual(
                graph_driver_evidence.validate(case.path, state, "S2", reference, historical=True)["result"], parsed
            )
            with self.assertRaisesRegex(ValueError, "attempt"):
                graph_driver_evidence.validate(case.path, state, "S2", reference)
            state["graph"]["active_wave"] = None
            state["revision"] += 1
            self.assertEqual(graph_driver_evidence.validate(case.path, state, "S2", reference)["result"], parsed)


if __name__ == "__main__":
    unittest.main()
