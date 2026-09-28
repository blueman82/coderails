"""Create disposable repositories and locate an already installed pinned sandbox."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from hooks.scripts.tests.lib.post_evals_fixture import ROOT, ArtifactCase
from scripts.sandbox.render_settings import render_settings


def cached_runtime() -> Path | None:
    """Find the exact local sandbox pin without fetching packages or using credentials."""
    cache = Path.home() / ".npm/_npx"
    for manifest in sorted(cache.glob("*/node_modules/@anthropic-ai/sandbox-runtime/package.json")):
        data = json.loads(manifest.read_text())
        if data.get("version") == "0.0.65":
            cli = manifest.parent / "dist/cli.js"
            if cli.is_file():
                return cli
    return None


class SandboxCase(ArtifactCase):
    """Operate only on fixture files and use the real locally cached runtime."""

    temporary_parent = "/private/tmp"

    def setUp(self) -> None:
        """Create a linked worktree, isolated home and narrow scratch directory."""
        super().setUp()
        self.directory = self.directory / "primary"
        self.directory.mkdir()
        self.node = shutil.which("node")
        self.runtime = cached_runtime()
        if platform.system() not in ("Darwin", "Linux") or not self.node or not self.runtime:
            self.skipTest("actual sandbox requires supported OS, Node and cached sandbox-runtime 0.0.65")
        self.repository()
        self.worktree = self.directory / "worktree"
        self.git("worktree", "add", "-b", "worker", str(self.worktree))
        self.home = self.directory / "home"
        self.scratch = self.directory / "scratch"
        self.bin = self.directory / "bin"
        for path in (self.home, self.home / ".claude/hooks", self.home / ".claude/plugins", self.scratch, self.bin):
            path.mkdir(parents=True, exist_ok=True)
        self.primary = self.directory / ".git"
        self.settings = self.scratch / "settings.json"
        self.environment = {
            key: value
            for key, value in os.environ.items()
            if key not in ("CLAUDE_CODE_SESSION_ID", "GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY")
        }
        self.environment.update(HOME=str(self.home), TMPDIR=str(self.scratch), PATH=f"{self.bin}:{os.environ['PATH']}")
        self.environment.update(SANDBOX_FIXTURE_NODE=str(self.node), SANDBOX_FIXTURE_CLI=str(self.runtime))
        source = Path(__file__).with_name("sandbox_worker_fixture.py").read_text().split("\n", 1)[1]
        for name in ("npx", "gh", "claude"):
            executable = self.bin / name
            executable.write_text(f"#!{sys.executable}\n{source}")
            executable.chmod(0o755)
        self.project_state = Path(f"/private/tmp/claude-{os.getuid()}") / str(self.worktree).replace("/", "-")
        self.addCleanup(self.cleanup_project_state)

    def cleanup_project_state(self) -> None:
        """Remove only this fixture's empty provider state directory."""
        if self.project_state.is_dir():
            self.project_state.rmdir()

    def render(self) -> None:
        """Render the production policy under the fixture environment."""
        from unittest.mock import patch

        with patch.dict(os.environ, self.environment, clear=True):
            render_settings(str(self.worktree), str(self.scratch), str(self.primary), str(self.settings))

    def sandbox(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        """Run actual srt with no package-manager network or provider calls."""
        return subprocess.run(
            [str(self.node), str(self.runtime), "--settings", str(self.settings), "--", *arguments],
            cwd=self.worktree,
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )

    def spawn(self, mode: str) -> subprocess.CompletedProcess[str]:
        """Exercise the production launcher with real srt and an inert worker."""
        prompt = self.directory / "prompt.txt"
        prompt.write_text("fixture worker prompt\n")
        environment = {**self.environment, "SANDBOX_FIXTURE_MODE": mode, "CODERAILS_HEADLESS_RUN": "1"}
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/sandbox/spawn_sandboxed_worker.py"),
                str(self.worktree),
                str(prompt),
                "fixture-model",
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
