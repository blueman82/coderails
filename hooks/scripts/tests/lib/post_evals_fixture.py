"""Shared isolated artifacts for the workflow eval contract tests."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.lib.artifact_io import JsonObject, read_object, write_object

ROOT = Path(__file__).resolve().parents[4]


def command(source: str) -> str:
    """Encode a real Python command in the product's configured command format."""
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(source)}"


def entry(identity: str = "E1") -> JsonObject:
    """Return a scripted content failure with a distinct failing control."""
    return {
        "id": identity,
        "priority": "P0",
        "mode": "scripted",
        "status": "pass",
        "evidence": "Observed command and negative control",
        "cmd": command("print('check')"),
        "negative_control": command("print('control'); raise SystemExit(1)"),
        "smoke": {"cmd_exit": 1, "negative_control_exit": 1},
    }


class ArtifactCase(unittest.TestCase):
    """Create an artifact in a directory outside the source repository."""

    temporary_parent: str | None = None

    def setUp(self) -> None:
        """Allocate a fresh suite for every test."""
        self.temporary = tempfile.TemporaryDirectory(prefix="coderails-eval-contract-", dir=self.temporary_parent)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "evals.json"
        self.data: JsonObject = {
            "verification_level": 1,
            "verification_justification": "Exercise real commands and their controls",
            "head_sha": "head",
            "task_ref": "192",
            "evals": [entry()],
        }
        self.save()
        self.directory.joinpath("progress.json").write_text('{"schema_version":3,"session_id":"s","loop_id":"l"}')

    def save(self) -> None:
        """Persist the current test input without invoking the grader."""
        write_object(self.path, self.data)

    def reload(self) -> JsonObject:
        """Read the actual product output after an operation."""
        return read_object(self.path)

    def cli(self, operation: str, *arguments: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
        """Run the real command entry point with bounded execution."""
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/post_evals.py"), operation, str(self.path), *arguments],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def git(self, *arguments: str) -> str:
        """Run Git solely in this test's local temporary repository."""
        result = subprocess.run(
            ["git", "-C", str(self.directory), *arguments], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()

    def repository(self) -> str:
        """Create a real local main commit without remotes or user hooks."""
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Eval test")
        self.git("config", "user.email", "eval@example.invalid")
        self.git("config", "core.hooksPath", str(self.directory / "no-hooks"))
        self.git("commit", "--allow-empty", "-m", "base")
        return self.git("rev-parse", "HEAD")

    def body(self, level: int, block: object) -> Path:
        """Create a marker and a literal JSON fence for embed validation."""
        path = self.directory / "body.md"
        marker = f"<!-- coderails-eval-summary v1 pr=192 head_sha=head result=GO verification_level={level} -->"
        path.write_text(f"{marker}\n```json\n{json.dumps(block)}\n```\n")
        return path
