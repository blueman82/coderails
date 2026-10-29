"""Check OAuth-only settings and credential filtering at the child boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"
sys.path.insert(0, str(SCRIPTS))
import graph_driver_codex  # noqa: E402

CANARIES = {
    name: "synthetic-" + name
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "CODEX_API_KEY",
        "CODEX_ACCESS_TOKEN",
        "OPENAI_BASE_URL",
        "CODEX_AUTHAPI_BASE_URL",
    )
}


class DriverOAuthTests(unittest.TestCase):
    """Run a synthetic Codex process, never an authenticated model request."""

    def test_every_launch_filters_credentials_and_forces_chatgpt(self) -> None:
        """Ordinary and every guarded role reach the CLI with only OAuth selected."""
        root = Path(__file__).resolve().parents[2]
        agents = json.loads((root / "packages/codex/capabilities/profiles.json").read_text())["agents"]
        guarded = [
            name
            for name, grants in agents.items()
            if {"repo.inspect", "diff.read", "tests.run", "pr.comment", "cmd.run"} & set(grants)
            and not {"shell.raw", "worktree.write"} & set(grants)
        ]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            tools = base / "bin"
            tools.mkdir()
            capture = base / "capture.json"
            child = tools / "codex"
            child.write_text(
                "#!/usr/bin/env python3\nimport json, os, sys\nfrom pathlib import Path\n"
                f"Path({str(capture)!r}).write_text(json.dumps({{'argv': sys.argv, 'env': sorted(os.environ)}}))\n"
            )
            child.chmod(0o755)
            for role in ["loop-worker", *guarded]:
                with self.subTest(role=role):
                    artifact = base / role
                    artifact.mkdir()
                    prompt = artifact / "prompt.txt"
                    prompt.write_text("synthetic source-only OAuth probe\n")
                    with patch.dict(
                        os.environ,
                        {
                            **CANARIES,
                            "PATH": f"{tools}:{os.environ['PATH']}",
                            "HOME": str(base),
                            "CODEX_HOME": str(base),
                        },
                        clear=True,
                    ):
                        argv, environment, _ = graph_driver_codex.command(prompt, artifact, role=role)
                        run = subprocess.run(
                            argv,
                            input=b"synthetic source-only OAuth probe\n",
                            env=environment,
                            capture_output=True,
                            check=False,
                        )
                    self.assertEqual(run.returncode, 0, run.stderr)
                    observed = json.loads(capture.read_text())
                    self.assertEqual(set(observed["env"]) & set(CANARIES), set())
                    self.assertIn('forced_login_method="chatgpt"', observed["argv"])
                    self.assertIn('model_provider="openai"', observed["argv"])


if __name__ == "__main__":
    unittest.main()
