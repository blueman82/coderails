"""The Codex worker process has a fixed sandbox and a narrow environment."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from packages.codex.scripts import codex_worker


class CodexWorkerTests(unittest.TestCase):
    """Check the bounded Codex worker process contract."""

    def setUp(self) -> None:
        """Create a disposable feature checkout for each test."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        subprocess.run(["git", "init", "-q", str(self.checkout)], check=True)
        subprocess.run(["git", "-C", str(self.checkout), "checkout", "-q", "-b", "feature/probe"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(self.checkout),
                "-c",
                "user.name=Probe",
                "-c",
                "user.email=probe@example.invalid",
                "commit",
                "--allow-empty",
                "-qm",
                "probe",
            ],
            check=True,
        )
        self.scratch = self.checkout / ".coderails-worker"
        self.scratch.mkdir()
        self.schema = self.scratch / "schema.json"
        self.schema.write_text(json.dumps({"type": "object"}))
        self.final = self.scratch / "final.json"

    def test_command_forces_sandbox_and_keeps_outputs_in_checkout(self) -> None:
        """Require the sandbox flags and local result paths."""
        argv = codex_worker.command(self.checkout, self.schema, self.final, executable="/fixture/codex")
        self.assertEqual(argv[:5], ["/fixture/codex", "exec", "--ignore-user-config", "--ephemeral", "--sandbox"])
        self.assertEqual(argv[5], "workspace-write")
        self.assertEqual(argv[-1], "-")
        self.assertIn("features.multi_agent=false", argv)
        self.assertNotIn("danger-full-access", argv)
        with self.assertRaisesRegex(ValueError, "scratch directory"):
            codex_worker.command(self.checkout, self.schema, self.root / "outside.json", executable="/fixture/codex")

    def test_main_branch_and_project_config_refuse_before_launch(self) -> None:
        """Do not run on main or read project supplied exec controls."""
        subprocess.run(["git", "-C", str(self.checkout), "checkout", "-q", "-b", "main"], check=True)
        with self.assertRaisesRegex(ValueError, "feature checkout"):
            codex_worker.command(self.checkout, self.schema, self.final, executable="/fixture/codex")
        subprocess.run(["git", "-C", str(self.checkout), "checkout", "-q", "feature/probe"], check=True)
        (self.checkout / ".codex").mkdir()
        with self.assertRaisesRegex(ValueError, "executable controls"):
            codex_worker.command(self.checkout, self.schema, self.final, executable="/fixture/codex")

    def test_environment_excludes_synthetic_credentials(self) -> None:
        """Keep unrelated inherited credentials out of the child."""
        with patch.dict(os.environ, {"GH_TOKEN": "canary-github", "ANTHROPIC_API_KEY": "canary-anthropic"}):
            child = codex_worker.environment()
        self.assertNotIn("GH_TOKEN", child)
        self.assertNotIn("ANTHROPIC_API_KEY", child)
        self.assertNotIn("PYTHONPATH", child)

    def test_missing_cli_or_symlink_schema_refuses(self) -> None:
        """Fail before launch when the CLI or safe artifact path is unavailable."""
        with (
            patch.object(shutil, "which", return_value=None),
            self.assertRaisesRegex(ValueError, "unavailable"),
        ):
            codex_worker.command(self.checkout, self.schema, self.final)
        alias = self.scratch / "alias.json"
        alias.symlink_to(self.schema)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            codex_worker.command(self.checkout, alias, self.final, executable="/fixture/codex")

    def test_success_without_terminal_trace_refuses(self) -> None:
        """A child exit cannot report success when its result was not recorded."""
        prompt = self.scratch / "prompt.txt"
        prompt.write_text("fixture")
        with (
            patch.object(codex_worker, "command", return_value=["fixture"]),
            patch.object(codex_worker, "trace", side_effect=[True, False]),
            patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0)),
            self.assertRaisesRegex(ValueError, "terminal trace"),
        ):
            codex_worker.run(
                self.checkout, prompt, self.schema, self.scratch / "output.jsonl", self.final, "default", "session"
            )


if __name__ == "__main__":
    unittest.main()
