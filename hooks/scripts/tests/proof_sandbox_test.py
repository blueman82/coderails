"""Run frozen proof commands under the real pinned sandbox."""

from __future__ import annotations

import json
import math
import os
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.post_evals_fixture import ROOT
from hooks.scripts.tests.lib.sandbox_fixture import cached_runtime
from scripts.lib import proof as controller
from scripts.lib import proof_results


class ProofSandboxTests(unittest.TestCase):
    """A proof reads the checkout but cannot change host files or use the network."""

    def setUp(self) -> None:
        """Create one disposable area for test inputs and canaries."""
        self.space = tempfile.TemporaryDirectory(prefix="proof-sandbox-test.")
        self.addCleanup(self.space.cleanup)
        self.directory = Path(self.space.name)

    def run_proof(
        self,
        runner: Path,
        cmd: str,
        *,
        path: str | None = None,
        expected_code: int = 0,
        stdout_contains: tuple[str, ...] = ("ok",),
    ) -> subprocess.CompletedProcess[str]:
        """Freeze one proof, then run it through the selected provider CLI."""
        state = self.directory / f"state-{len(list(self.directory.glob('state-*')))}"
        state.mkdir()
        self.last_state = state
        (state / "progress.json").write_text(json.dumps({"session_id": "test", "loop_id": "test"}))
        (state / "proof.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "proofs": [
                        {
                            "id": "P",
                            "cmd": cmd,
                            "expect": {"exit_code": expected_code, "stdout_contains": list(stdout_contains)},
                        }
                    ],
                }
            )
        )
        freeze = subprocess.run(
            [sys.executable, str(runner), "freeze", str(state)], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(freeze.returncode, 0, freeze.stderr)
        env = os.environ.copy()
        if path is not None:
            env["PATH"] = path
        return subprocess.run(
            [sys.executable, str(runner), "run", str(state), "--all"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )

    def test_nested_write_is_denied_by_both_provider_runners(self) -> None:
        """An interpreter cannot change a file outside the sandbox scratch."""
        if not cached_runtime() or not shutil.which("npx"):
            self.skipTest("the pinned runtime is not cached")
        for runner in (ROOT / "scripts/lib/proof.py", ROOT / "packages/codex/scripts/lib/proof.py"):
            with self.subTest(runner=runner):
                target = self.directory / "host-marker"
                cmd = f"{shlex.quote(sys.executable)} -c " + shlex.quote(
                    f"from pathlib import Path; Path({str(target)!r}).write_text('bad'); print('ok')"
                )
                result = self.run_proof(runner, cmd)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(target.exists(), result.stdout + result.stderr)

    def test_loopback_connection_is_denied_by_both_provider_runners(self) -> None:
        """A child process cannot connect to a local listener."""
        if not cached_runtime() or not shutil.which("npx"):
            self.skipTest("the pinned runtime is not cached")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            cmd = f"{shlex.quote(sys.executable)} -c " + shlex.quote(
                f"import socket; socket.create_connection(('127.0.0.1', {port}), 1).close(); print('ok')"
            )
            for runner in (ROOT / "scripts/lib/proof.py", ROOT / "packages/codex/scripts/lib/proof.py"):
                with self.subTest(runner=runner):
                    result = self.run_proof(runner, cmd)
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_runtime_default_log_path_is_denied(self) -> None:
        """The runtime's implicit npm log grant must not reach the proof child."""
        if not cached_runtime() or not shutil.which("npx"):
            self.skipTest("the pinned runtime is not cached")
        target = Path.home() / ".npm/_logs" / f"coderails-proof-canary-{uuid.uuid4().hex}"
        self.addCleanup(target.unlink, missing_ok=True)
        cmd = f"{shlex.quote(sys.executable)} -c " + shlex.quote(
            f"from pathlib import Path; Path({str(target)!r}).write_text('bad'); print('ok')"
        )
        for runner in (ROOT / "scripts/lib/proof.py", ROOT / "packages/codex/scripts/lib/proof.py"):
            with self.subTest(runner=runner):
                result = self.run_proof(runner, cmd)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(target.exists(), result.stdout + result.stderr)

    def test_runtime_default_tmp_path_is_denied(self) -> None:
        """The runtime's implicit shared temporary grant is removed."""
        if not cached_runtime() or not shutil.which("npx"):
            self.skipTest("the pinned runtime is not cached")
        shared = Path("/tmp/claude")
        existed = shared.exists()
        shared.mkdir(exist_ok=True)
        if not existed:
            self.addCleanup(shared.rmdir)
        target = shared / f"coderails-proof-canary-{uuid.uuid4().hex}"
        self.addCleanup(target.unlink, missing_ok=True)
        cmd = f"{shlex.quote(sys.executable)} -c " + shlex.quote(
            f"from pathlib import Path; Path({str(target)!r}).write_text('bad'); print('ok')"
        )
        for runner in (ROOT / "scripts/lib/proof.py", ROOT / "packages/codex/scripts/lib/proof.py"):
            with self.subTest(runner=runner):
                result = self.run_proof(runner, cmd)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(target.exists(), result.stdout + result.stderr)

    def test_compound_read_only_command_keeps_stdout_expectation(self) -> None:
        """The controller keeps original command output and shell chaining."""
        if not cached_runtime() or not shutil.which("npx"):
            self.skipTest("the pinned runtime is not cached")
        cmd = "printf first; printf ' ok\\n'"
        for runner in (ROOT / "scripts/lib/proof.py", ROOT / "packages/codex/scripts/lib/proof.py"):
            with self.subTest(runner=runner):
                result = self.run_proof(runner, cmd)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('"verdict": "satisfied"', result.stdout)
                rows = proof_results.read_rows(self.last_state / proof_results.RESULTS_NAME)
                self.assertEqual(rows[-1]["cmd_sha256"], proof_results.sha(cmd))
                self.assertEqual(rows[-1]["stdout_sha256"], proof_results.sha("first ok\n"))

    def test_missing_runtime_fails_closed(self) -> None:
        """A matching nonzero exit cannot hide a missing sandbox."""
        bin_dir = self.directory / "bin"
        bin_dir.mkdir()
        git = shutil.which("git")
        assert git is not None
        (bin_dir / "git").symlink_to(git)
        target = self.directory / "host-marker"
        cmd = f"{shlex.quote(sys.executable)} -c " + shlex.quote(
            f"from pathlib import Path; Path({str(target)!r}).write_text('bad'); print('ok')"
        )
        for runner in (ROOT / "scripts/lib/proof.py", ROOT / "packages/codex/scripts/lib/proof.py"):
            with self.subTest(runner=runner):
                result = self.run_proof(runner, cmd, path=str(bin_dir), expected_code=1, stdout_contains=())
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(target.exists(), result.stdout + result.stderr)
                self.assertIn("sandbox_unavailable", result.stdout + result.stderr)
                rows = proof_results.read_rows(self.last_state / proof_results.RESULTS_NAME)
                self.assertEqual(rows[-1]["verdict"], "sandbox_unavailable")

    def test_freeze_refuses_unsafe_timeout_before_start(self) -> None:
        """Both providers reject timeouts that could fail after child creation."""
        for runner in (ROOT / "scripts/lib/proof.py", ROOT / "packages/codex/scripts/lib/proof.py"):
            for timeout in (math.nan, math.inf, -math.inf, 3601, 1e308):
                with self.subTest(runner=runner, timeout=timeout):
                    state = self.directory / f"timeout-{uuid.uuid4().hex}"
                    state.mkdir()
                    (state / "proof.json").write_text(
                        json.dumps(
                            {
                                "schema_version": 2,
                                "proofs": [
                                    {"id": "P", "cmd": "true", "timeout_s": timeout, "expect": {"exit_code": 0}}
                                ],
                            }
                        )
                    )
                    result = subprocess.run(
                        [sys.executable, str(runner), "freeze", str(state)],
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("timeout_s", result.stderr)
                    self.assertFalse((state / proof_results.RESULTS_NAME).exists())

    def test_scratch_preparation_failure_replaces_prior_pass(self) -> None:
        """A scratch creation error must append a refusal after an earlier pass."""
        results = self.directory / proof_results.RESULTS_NAME
        proof_results.append(results, kind="run", proof_id="P", verdict="satisfied")
        entry = {"id": "P", "cmd": "printf ok", "expect": {"exit_code": 0}}
        run_one = controller._run_one  # pyright: ignore[reportPrivateUsage]
        with patch("scripts.lib.proof.tempfile.TemporaryDirectory", side_effect=OSError("no scratch")):
            verdict = run_one(entry, "frozen", ("test", "test"), results)
        self.assertEqual(verdict, "sandbox_unavailable")
        self.assertEqual(proof_results.read_rows(results)[-1]["verdict"], "sandbox_unavailable")


if __name__ == "__main__":
    unittest.main()
