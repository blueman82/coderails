"""A driver worker is authorized once against its exact issued prompt."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from hooks.scripts.tests.graph_convert_test import SCRIPTS, Case  # noqa: E402


def frozen_evals() -> dict[str, Any]:
    """Make a disposable loop suite for the Codex dispatch gate."""
    return {
        "scope": "loop",
        "task_ref": "L",
        "session_id": "S",
        "loop_id": "L",
        "verification_level": 1,
        "verification_justification": "test suite",
        "frozen_sha": "fixture",
        "evals": [{"id": "E1", "priority": "P0", "mode": "agent-run"}],
        "result": None,
        "grading": None,
    }


class DriverAuthorizationTests(unittest.TestCase):
    """Use both public graph commands and their real state files."""

    def test_authorize_binds_prompt_role_and_single_use_id(self) -> None:
        """A changed prompt, wrong role or replay never consumes the slot."""
        with tempfile.TemporaryDirectory() as directory:
            for provider in ("claude", "codex"):
                case = Case(provider, Path(directory))
                self.assertEqual(case.graph("convert").returncode, 0)
                self.assertEqual(case.graph("cutover-driver").returncode, 0)
                if provider == "codex":
                    case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
                opened = subprocess.run(
                    [sys.executable, str(SCRIPTS[provider]), "begin-driver-wave", str(case.path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(opened.returncode, 0, (provider, opened.stderr))
                dispatch = json.loads(opened.stdout)["dispatches"][0]
                dispatch_id = dispatch["dispatch_id"]
                role = case.read()["graph"]["dispatches"][dispatch_id]["contract"]["role"]
                prompt = case.path.parent / "driver-evidence" / dispatch_id / "prompt.txt"
                prompt.parent.mkdir(parents=True)
                original = dispatch["prompt_prefix"] + "\n" + dispatch["prompt_sections"] + "\n"
                prompt.write_text(original)
                base = [
                    sys.executable,
                    str(SCRIPTS[provider]),
                    "authorize-driver",
                    str(case.path),
                    "--session",
                    "S",
                    "--dispatch-id",
                    dispatch_id,
                    "--prompt-file",
                    str(prompt),
                    "--driver-run-id",
                    "run-1",
                ]
                before = case.path.read_bytes()
                wrong_role = subprocess.run([*base, "--role", "wrong"], capture_output=True, text=True, check=False)
                self.assertNotEqual(wrong_role.returncode, 0)
                self.assertEqual(case.path.read_bytes(), before)
                prompt.write_text(original.replace("CODERAILS_GRAPH_CONTRACT v2", "BROKEN CONTRACT"))
                altered = subprocess.run([*base, "--role", role], capture_output=True, text=True, check=False)
                self.assertNotEqual(altered.returncode, 0)
                self.assertEqual(case.path.read_bytes(), before)
                prompt.write_text(original)
                accepted = subprocess.run([*base, "--role", role], capture_output=True, text=True, check=False)
                self.assertEqual(accepted.returncode, 0, (provider, accepted.stderr))
                authorized = case.read()["graph"]["dispatches"][dispatch_id]["authorized"]
                self.assertEqual(authorized["driver_run_id"], "run-1")
                self.assertEqual(authorized["prompt_sha256"], hashlib.sha256(original.encode()).hexdigest())
                once = case.path.read_bytes()
                replay = subprocess.run([*base, "--role", role], capture_output=True, text=True, check=False)
                self.assertNotEqual(replay.returncode, 0)
                self.assertEqual(case.path.read_bytes(), once)


if __name__ == "__main__":
    unittest.main()
