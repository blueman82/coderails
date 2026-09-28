"""Preserve Git executable modes and isolated Claude install behavior in fixture trees."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.run_all import isolated_environment
from scripts.installer.modes import arm_scripts

ROOT = Path(__file__).resolve().parents[3]


class InstallModeSweepTests(unittest.TestCase):
    """Never install into the real HOME or create worktrees in the source repository."""

    def test_tracked_modes_and_untracked_fallback(self) -> None:
        """Fix stale bits in both directions while preserving no-index execution fallback."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library, executable = root / "scripts/lib/config.py", root / "scripts/push.py"
            library.parent.mkdir(parents=True)
            library.write_text('"""Fixture imported module."""\n')
            executable.write_text("#!/usr/bin/env python3\n")
            library.chmod(0o644)
            executable.chmod(0o755)
            subprocess.run(["git", "init", "-q", str(root)], check=True, env=isolated_environment())
            subprocess.run(["git", "-C", str(root), "add", "scripts"], check=True, env=isolated_environment())
            subprocess.run(
                ["git", "-C", str(root), "update-index", "--chmod=-x", "scripts/lib/config.py"],
                check=True,
                env=isolated_environment(),
            )
            subprocess.run(
                ["git", "-C", str(root), "update-index", "--chmod=+x", "scripts/push.py"],
                check=True,
                env=isolated_environment(),
            )
            untracked = root / "scripts/lib/scratch.py"
            untracked.write_text('"""Fixture untracked module."""\n')
            untracked.chmod(0o644)
            library.chmod(0o755)
            executable.chmod(0o644)
            arm_scripts(root, dry_run=True)
            self.assertTrue(library.stat().st_mode & 0o111)
            self.assertFalse(executable.stat().st_mode & 0o111)
            arm_scripts(root, dry_run=False)
            self.assertFalse(library.stat().st_mode & 0o111)
            self.assertTrue(executable.stat().st_mode & 0o111)
            self.assertTrue(untracked.stat().st_mode & 0o111)

    def test_actual_no_git_install_mutates_only_fixture_home(self) -> None:
        """Run the actual Python CLI in a minimal release tree with synthetic HOME."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ("scripts/installer", "scripts/lib"):
                shutil.copytree(ROOT / folder, root / folder, ignore=shutil.ignore_patterns("*.sh", "__pycache__"))
            shutil.copyfile(ROOT / "install.py", root / "install.py")
            for relative, content in {
                "packages/graph-semantics/graph_semantics.py": '"""Fixture semantics."""\n',
                "instructions/self-checking-discipline.md": "preamble\n## Self-Checking Discipline\nfixture rules\n",
                "commands/workflow.md": "replacement",
                "starter-memory/feedback_fixture.md": "memory fixture",
            }.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            home = root / "fixture-home"
            settings = home / ".claude/settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({"extraKnownMarketplaces": {"workflow-tools": {}, "other": {}}}))
            known = home / ".claude/plugins/known_marketplaces.json"
            known.parent.mkdir()
            known.write_text('{"workflow-tools": {}, "other": {}}')
            command = home / ".claude/commands/workflow.md"
            command.parent.mkdir()
            command.write_text("personal command")
            environment = dict(isolated_environment(), HOME=str(home), PYTHONDONTWRITEBYTECODE="1")
            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "install.py"),
                    "--no-integrity-gate",
                    "--memory-target",
                    str(home / "memory"),
                ],
                cwd=root,
                env=environment,
                input="n\n",
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            registry = json.loads(settings.read_text())["extraKnownMarketplaces"]
            self.assertNotIn("workflow-tools", registry)
            self.assertIn("other", registry)
            self.assertEqual(registry["coderails"]["source"]["path"], str(root.resolve()))
            self.assertEqual(json.loads(known.read_text()), {"other": {}})
            self.assertIn("## Self-Checking Discipline", (home / ".claude/CLAUDE.md").read_text())
            self.assertEqual(command.read_text(), "personal command")
            self.assertEqual(len(list(command.parent.iterdir())), 1)
            self.assertEqual((home / "memory/feedback_fixture.md").read_text(), "memory fixture")
            self.assertTrue((root / "scripts/lib/config.py").stat().st_mode & 0o111)


if __name__ == "__main__":
    unittest.main()
