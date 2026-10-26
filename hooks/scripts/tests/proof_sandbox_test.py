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
from typing import Any
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
        cwd: Path = ROOT,
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
                    "session_id": "test",
                    "loop_id": "test",
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
            [sys.executable, str(runner), "freeze", str(state)], cwd=cwd, capture_output=True, text=True, check=False
        )
        self.assertEqual(freeze.returncode, 0, freeze.stderr)
        env = os.environ.copy()
        if path is not None:
            env["PATH"] = path
        return subprocess.run(
            [sys.executable, str(runner), "run", str(state), "--all"],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )

    def source_repo(self) -> Path:
        """Make one committed checkout for hostile local-package and dirty-source controls."""
        repo = self.directory / f"repo-{uuid.uuid4().hex}"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
        (repo / "claim.txt").write_text("bad\n")
        subprocess.run(["git", "-C", str(repo), "add", "claim.txt"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
        return repo

    def test_repository_package_cannot_run_before_proof_sandbox(self) -> None:
        """A matching local npm package must not execute with controller permissions."""
        if not cached_runtime() or not shutil.which("npx"):
            self.skipTest("the pinned runtime is not cached")
        for runner in (ROOT / "scripts/lib/proof.py", ROOT / "packages/codex/scripts/lib/proof.py"):
            with self.subTest(runner=runner):
                repo = self.source_repo()
                package = repo / "node_modules/@anthropic-ai/sandbox-runtime"
                package.mkdir(parents=True)
                (package / "package.json").write_text(
                    json.dumps({"name": "@anthropic-ai/sandbox-runtime", "version": "0.0.65", "bin": {"srt": "cli.js"}})
                )
                cli = package / "cli.js"
                cli.write_text("#!/usr/bin/env node\nrequire('fs').writeFileSync('canary', 'escaped');\n")
                cli.chmod(0o755)
                bin_dir = repo / "node_modules/.bin"
                bin_dir.mkdir()
                (bin_dir / "srt").symlink_to("../@anthropic-ai/sandbox-runtime/cli.js")
                result = self.run_proof(runner, "printf ok", cwd=repo)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse((repo / "canary").exists())

    def test_repository_path_cannot_supply_controller_binaries(self) -> None:
        """A repository PATH entry must not run git or node before the sandbox starts."""
        if not cached_runtime():
            self.skipTest("the pinned runtime is not cached")
        for runner in (ROOT / "scripts/lib/proof.py", ROOT / "packages/codex/scripts/lib/proof.py"):
            with self.subTest(runner=runner):
                repo = self.source_repo()
                bin_dir = repo / "tools/bin"
                bin_dir.mkdir(parents=True)
                for name in ("git", "node"):
                    binary = bin_dir / name
                    binary.write_text(
                        f"#!/bin/sh\nprintf attacked > {shlex.quote(str(repo / (name + '-canary')))}\nexit 92\n"
                    )
                    binary.chmod(0o755)
                result = self.run_proof(
                    runner, "printf ok", cwd=repo, path=str(bin_dir) + os.pathsep + os.environ["PATH"]
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse((repo / "git-canary").exists())
                self.assertFalse((repo / "node-canary").exists())

    def test_committed_symlink_cannot_read_mutable_external_target(self) -> None:
        """A source link cannot make the proof read bytes outside the committed tree."""
        if not cached_runtime():
            self.skipTest("the pinned runtime is not cached")
        for runner in (ROOT / "scripts/lib/proof.py", ROOT / "packages/codex/scripts/lib/proof.py"):
            with self.subTest(runner=runner):
                repo = self.source_repo()
                outside = self.directory / f"target-{uuid.uuid4().hex}"
                outside.write_text("good\n")
                (repo / "link.txt").symlink_to(outside)
                subprocess.run(["git", "-C", str(repo), "add", "link.txt"], check=True)
                subprocess.run(["git", "-C", str(repo), "commit", "-qm", "link"], check=True)
                result = self.run_proof(runner, "cat link.txt", cwd=repo, stdout_contains=("good",))
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                row = proof_results.read_rows(self.last_state / proof_results.RESULTS_NAME)[-1]
                self.assertEqual(row["verdict"], "sandbox_unavailable")

    def test_proof_cannot_pass_on_uncommitted_source_then_restore_it(self) -> None:
        """A passing row must cover committed source bytes rather than a temporary file edit."""
        if not cached_runtime() or not shutil.which("npx"):
            self.skipTest("the pinned runtime is not cached")
        for runner in (ROOT / "scripts/lib/proof.py", ROOT / "packages/codex/scripts/lib/proof.py"):
            with self.subTest(runner=runner):
                repo = self.source_repo()
                (repo / "claim.txt").write_text("good\n")
                result = self.run_proof(runner, "cat claim.txt", cwd=repo, stdout_contains=("good",))
                self.assertIn("expect_mismatch", result.stdout + result.stderr)
                (repo / "claim.txt").write_text("bad\n")
                document = json.loads((self.last_state / "proof.json").read_text())
                previous = Path.cwd()
                try:
                    os.chdir(repo)
                    offenders, _ = proof_results.verify(
                        document,
                        self.last_state / proof_results.RESULTS_NAME,
                        {"session_id": "test", "loop_id": "test"},
                    )
                finally:
                    os.chdir(previous)
                self.assertTrue(offenders, "restored code must not inherit a proof pass from edited bytes")

    def test_proof_cannot_read_mutable_checkout_by_absolute_path(self) -> None:
        """An absolute path cannot bypass the committed source snapshot."""
        if not cached_runtime() or not shutil.which("npx"):
            self.skipTest("the pinned runtime is not cached")
        for runner in (ROOT / "scripts/lib/proof.py", ROOT / "packages/codex/scripts/lib/proof.py"):
            with self.subTest(runner=runner):
                repo = self.source_repo()
                (repo / "claim.txt").write_text("good\n")
                result = self.run_proof(
                    runner, f"cat {shlex.quote(str(repo / 'claim.txt'))}", cwd=repo, stdout_contains=("good",)
                )
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                row = proof_results.read_rows(self.last_state / proof_results.RESULTS_NAME)[-1]
                self.assertEqual(row["verdict"], "failed")

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

    def test_large_output_records_refusal_without_unbounded_capture(self) -> None:
        """Both controllers stop high output and mark recorded output hashes as partial."""
        if not cached_runtime() or not shutil.which("npx"):
            self.skipTest("the pinned runtime is not cached")
        cmd = f"{shlex.quote(sys.executable)} -c " + shlex.quote("print('x' * 2000000)")
        for runner in (ROOT / "scripts/lib/proof.py", ROOT / "packages/codex/scripts/lib/proof.py"):
            with self.subTest(runner=runner):
                result = self.run_proof(runner, cmd, stdout_contains=())
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                row = proof_results.read_rows(self.last_state / proof_results.RESULTS_NAME)[-1]
                self.assertEqual(row["verdict"], "output_limit")
                self.assertIn("partial output", row["excerpt"])
                self.assertLessEqual(len(row["excerpt"]), controller.EXCERPT_CAP)

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
                                "session_id": "test",
                                "loop_id": "test",
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

    def test_freeze_refuses_excess_malformed_withdrawals_and_blank_identity(self) -> None:
        """Both controllers reject 101 entries, an object array, and missing loop identity."""
        entry = {"id": "P", "cmd": "true", "expect": {"exit_code": 0}}
        valid = {"schema_version": 2, "session_id": "test", "loop_id": "test", "proofs": [entry]}
        invalid: tuple[dict[str, Any], ...] = (
            valid | {"proofs": [{**entry, "id": f"P{i}"} for i in range(101)]},
            valid
            | {
                "withdrawn_proofs": [
                    {"id": f"W{i}", "cmd": "false", "expect": {"exit_code": 0}, "withdrawn_reason": "failed"}
                    for i in range(100)
                ]
            },
            valid | {"withdrawn_proofs": {}},
            valid | {"session_id": ""},
            valid | {"loop_id": " "},
            {key: value for key, value in valid.items() if key != "session_id"},
        )
        for runner in (ROOT / "scripts/lib/proof.py", ROOT / "packages/codex/scripts/lib/proof.py"):
            for document in invalid:
                with self.subTest(runner=runner, case=list(document)):
                    state = self.directory / f"invalid-{uuid.uuid4().hex}"
                    state.mkdir()
                    (state / "proof.json").write_text(json.dumps(document))
                    result = subprocess.run(
                        [sys.executable, str(runner), "freeze", str(state)],
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
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
