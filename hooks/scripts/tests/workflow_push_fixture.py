"""Local-only repository and executable fixtures for the actual push CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from hooks.scripts.tests.run_all import isolated_environment

ROOT = Path(__file__).resolve().parents[3]


class PushFixture:
    """Contain all Git writes and provider stubs in one caller-owned temporary tree."""

    def __init__(self, root: Path) -> None:
        """Create a feature checkout with a local-only push URL and inert gh."""
        self.root = root
        self.origin = root / "origin.git"
        self.repo = root / "repo"
        self.bin = root / "bin"
        self.bin.mkdir()
        self.log = root / "push-argv.jsonl"
        self.real_git = shutil.which("git") or "git"
        self.environment = dict(
            isolated_environment(),
            HOME=str(root / "home"),
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_ALLOW_PROTOCOL="file",
            GIT_TERMINAL_PROMPT="0",
            PYTHONDONTWRITEBYTECODE="1",
            PATH=str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
        )
        self.git(root, "init", "--bare", str(self.origin))
        self.git(root, "clone", str(self.origin), str(self.repo))
        self.git(self.repo, "config", "user.name", "Fixture")
        self.git(self.repo, "config", "user.email", "fixture@example.invalid")
        (self.repo / "base.txt").write_text("base")
        self.git(self.repo, "add", "base.txt")
        self.git(self.repo, "commit", "-m", "fixture initial")
        self.git(self.repo, "branch", "-M", "main")
        self.git(self.repo, "push", "-u", "origin", "main")
        self.git(self.repo, "remote", "set-head", "origin", "main")
        self.git(self.repo, "remote", "set-url", "origin", "https://github.com/fixture/repo.git")
        self.git(self.repo, "remote", "set-url", "--push", "origin", str(self.origin))
        self.git(self.repo, "checkout", "-b", "feature")
        self.stub(
            "gh", 'import sys\nif sys.argv[1:3] == ["pr", "create"]: print("https://github.com/fixture/repo/pull/1")\n'
        )

    def stub(self, name: str, body: str) -> None:
        """Write one inert executable using the current Python interpreter."""
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + body)
        path.chmod(0o755)

    def git(self, directory: Path, *arguments: str) -> str:
        """Execute actual Git against a fixture path with file protocol only."""
        result = subprocess.run(
            [self.real_git, "-C", str(directory), *arguments],
            env=self.environment,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def push(self, *arguments: str, mode: str = "") -> subprocess.CompletedProcess[str]:
        """Execute the real maintained CLI with optional display/transport controls."""
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/push.py"), *arguments],
            cwd=self.repo,
            env=dict(self.environment, GIT_FIXTURE_MODE=mode),
            capture_output=True,
            text=True,
        )

    def record_pushes(self) -> None:
        """Record literal push argv and optionally model dishonest transport output."""
        body = f"""import json, os, subprocess, sys
from pathlib import Path
real = {self.real_git!r}
args = sys.argv[1:]
if args and args[0] == "push":
    with Path({str(self.log)!r}).open("a") as stream:
        stream.write(json.dumps(args) + "\\n")
    if os.environ.get("GIT_FIXTURE_MODE") == "deceptive":
        raise SystemExit(0)
    result = subprocess.run([real, *args], capture_output=True)
    if result.returncode == 0 and os.environ.get("GIT_FIXTURE_MODE") == "remote-only":
        print("remote: fixture successful push")
    else:
        sys.stdout.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
    raise SystemExit(result.returncode)
os.execv(real, [real, *args])
"""
        self.stub("git", body)

    def push_arguments(self) -> list[list[str]]:
        """Read the fixture's emitted argument log after a push invocation."""
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def advance_remote(self) -> None:
        """Have a separate local clone advance feature without updating caller tracking refs."""
        scratch = self.root / "scratch"
        self.git(self.root, "clone", "--branch", "feature", str(self.origin), str(scratch))
        self.git(scratch, "config", "user.name", "Fixture")
        self.git(scratch, "config", "user.email", "fixture@example.invalid")
        (scratch / "remote.txt").write_text("other developer")
        self.git(scratch, "add", "remote.txt")
        self.git(scratch, "commit", "-m", "fixture remote advance")
        self.git(scratch, "push", "origin", "feature")
