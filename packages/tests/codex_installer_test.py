"""Exercise real provider installer entrypoints entirely inside private fixture trees."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
READ_ONLY = {
    "deploy-safety-reviewer",
    "design-scout",
    "disposition-scout",
    "preflight-scout",
    "source-auditor",
    "spec-reviewer",
}


class ProviderInstallerTests(unittest.TestCase):
    """Keep provider commands inert and test native state isolation and all agents."""

    def setUp(self) -> None:
        """Copy runtime assets and inert provider executables into an isolated release."""
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.base = Path(self.scratch.name)
        self.root = self.base / "release"
        for folder in ("scripts/installer", "scripts/lib", "packages/codex/agents"):
            shutil.copytree(ROOT / folder, self.root / folder, ignore=shutil.ignore_patterns("*.sh", "__pycache__"))
        shutil.copyfile(ROOT / "install.py", self.root / "install.py")
        for relative, content in {
            "packages/graph-semantics/graph_semantics.py": '"""Fixture semantics."""\n',
            "instructions/self-checking-discipline.md": "## Self-Checking Discipline\nfixture\n",
            "commands/workflow.md": "fixture",
            "starter-memory/feedback_fixture.md": "fixture",
        }.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.home = self.base / "home"
        self.home.mkdir()
        self.log = self.base / "provider.log"
        binary = self.base / "bin"
        binary.mkdir()
        for name in ("gh", "git", "claude"):
            path = binary / name
            path.write_text("#!/usr/bin/env python3\nraise SystemExit(0)\n")
            path.chmod(0o755)
        codex = binary / "codex"
        codex.write_text(
            "#!/usr/bin/env python3\nimport json,os,sys\nfrom pathlib import Path\n"
            "home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))\n"
            "assert home.is_dir(), 'provider home must exist before command'\n"
            "with open(os.environ['CODEX_LOG'],'a') as stream:\n"
            " stream.write(json.dumps(sys.argv[1:])+'\\n')\n"
        )
        codex.chmod(0o755)
        self.env = dict(
            os.environ,
            HOME=str(self.home),
            CODEX_LOG=str(self.log),
            PATH=str(binary) + os.pathsep + os.environ.get("PATH", ""),
            PYTHONDONTWRITEBYTECODE="1",
        )
        self.env.pop("CODEX_HOME", None)

    def install(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        """Run the unmodified entrypoint with closed stdin and a genuinely private HOME."""
        return subprocess.run(
            [sys.executable, str(self.root / "install.py"), *arguments],
            cwd=self.root,
            env=self.env,
            input="",
            text=True,
            capture_output=True,
        )

    def success(self, *arguments: str) -> str:
        """Require actual CLI success and expose its observable output."""
        result = self.install(*arguments)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_empty_home_default_claude(self) -> None:
        """An empty HOME bootstraps Claude alone and registers the exact release root."""
        self.assertEqual(list(self.home.iterdir()), [])
        before = (self.root / "packages/graph-semantics/graph_semantics.py").read_bytes()
        self.success("--no-integrity-gate")
        settings = json.loads((self.home / ".claude/settings.json").read_text())
        self.assertEqual(settings["extraKnownMarketplaces"]["coderails"]["source"]["path"], str(self.root.resolve()))
        self.assertFalse((self.home / ".codex").exists())
        self.assertFalse(self.log.exists())
        self.assertEqual((self.root / "packages/graph-semantics/graph_semantics.py").read_bytes(), before)
        for relative in (
            "skills/agentic-loop/scripts/graph_semantics.py",
            "packages/codex/skills/agentic-loop/scripts/graph_semantics.py",
        ):
            self.assertEqual((self.root / relative).read_bytes(), before)

    def test_provider_defaults_dry_run_and_invalid_options(self) -> None:
        """Defaults match Claude; rejected and dry-run commands do not mutate HOME."""
        self.assertEqual(self.success("--dry-run"), self.success("--provider", "claude", "--dry-run"))
        for arguments in (("--provider", "other"), ("--provider", "codex", "--memory-target", "unused")):
            self.assertNotEqual(self.install(*arguments, "--dry-run").returncode, 0)
        output = self.success("--provider", "codex", "--dry-run")
        self.assertIn("codex plugin marketplace add", output)
        self.assertIn("coderails-codex@coderails", output)
        self.assertIn("Codex skips plugin hooks until then", output)
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertFalse(self.log.exists())

    def test_codex_native_agents_reinstall_and_backup(self) -> None:
        """Every packaged agent stays provider-native and managed updates are atomic."""
        claude = self.home / ".claude"
        claude.mkdir()
        (claude / "sentinel").write_text("leave me alone\n")
        output = self.success("--provider", "codex")
        self.assertEqual(list(claude.iterdir()), [claude / "sentinel"])
        self.assertEqual((claude / "sentinel").read_text(), "leave me alone\n")
        self.assertEqual(
            [json.loads(line) for line in self.log.read_text().splitlines()],
            [
                ["plugin", "marketplace", "add", str(self.root.resolve())],
                ["plugin", "add", "coderails-codex@coderails"],
            ],
        )
        self.assertIn("Codex skips plugin hooks until you review and trust them.", output)
        self.assertIn("Start a fresh Codex session, run /hooks", output)
        agents = self.home / ".codex/agents"
        self.assertEqual(len(list(agents.glob("*.toml"))), 10)
        for source in (self.root / "packages/codex/agents").glob("*.toml"):
            text = source.read_text()
            target = agents / source.name
            self.assertFalse(source.is_symlink())
            self.assertFalse(target.is_symlink())
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertIn("# Managed by Coderails Codex plugin", text)
            self.assertRegex(text, r'(?m)^name = ".+"$')
            self.assertRegex(text, r'(?m)^description = ".+"$')
            self.assertIn('developer_instructions = """', text)
            self.assertNotRegex(text.lower(), r"claude|pr-review-toolkit|/security-review")
            if source.stem in READ_ONLY:
                self.assertEqual(text.count('sandbox_mode = "read-only"'), 1)
            else:
                self.assertNotIn("sandbox_mode =", text)
        managed = agents / "loop-worker.toml"
        inode = managed.stat().st_ino
        self.success("--provider", "codex")
        self.assertEqual(managed.stat().st_ino, inode)
        managed.write_text(managed.read_text() + "\nstale managed copy\n")
        self.success("--provider", "codex")
        backups = list(agents.glob("loop-worker.toml.coderails-backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertIn("stale managed copy", backups[0].read_text())
        self.assertEqual(managed.read_bytes(), (self.root / "packages/codex/agents/loop-worker.toml").read_bytes())

    def test_explicit_home_and_unrelated_collision(self) -> None:
        """Explicit homes exist before provider invocation; collisions reject all mutation."""
        explicit = self.base / "explicit-codex"
        self.env["CODEX_HOME"] = str(explicit)
        self.assertFalse(explicit.exists())
        self.success("--provider", "codex")
        self.assertEqual(len(self.log.read_text().splitlines()), 2)
        collision = self.base / "collision"
        self.env["CODEX_HOME"] = str(collision)
        agents = collision / "agents"
        agents.mkdir(parents=True)
        target = agents / "design-scout.toml"
        target.write_text("unrelated local agent\n")
        self.log.unlink()
        result = self.install("--provider", "codex")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(agents.iterdir()), [target])
        self.assertEqual(target.read_text(), "unrelated local agent\n")
        self.assertFalse(self.log.exists())
        self.assertNotIn("Start a fresh Codex session", result.stdout)


if __name__ == "__main__":
    unittest.main()
