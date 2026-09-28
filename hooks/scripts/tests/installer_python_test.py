"""Exercise provider install refusal, materialization and dotfile preservation locally."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.installer import codex, files

ROOT = Path(__file__).resolve().parents[3]


class InstallerTests(unittest.TestCase):
    """Use isolated homes and mocked provider commands for installation controls."""

    def test_materialization_and_dry_run(self) -> None:
        """Generate independent identical copies and never write in dry-run mode."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "packages/graph-semantics/graph_semantics.py"
            source.parent.mkdir(parents=True)
            source.write_text("fixture canonical\n")
            files.materialize(root, dry_run=True)
            self.assertFalse((root / "skills").exists())
            files.materialize(root, dry_run=False)
            for relative in files.SEMANTIC_TARGETS:
                self.assertEqual((root / relative).read_bytes(), source.read_bytes())
                self.assertNotEqual((root / relative).stat().st_ino, source.stat().st_ino)

    def test_test_output_copy_is_preflighted_before_any_materialization(self) -> None:
        """A redirected helper target cannot cause partially updated provider bundles."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "packages/graph-semantics/graph_semantics.py"
            source.parent.mkdir(parents=True)
            source.write_text("canonical graph\n")
            output = root / "hooks/scripts/test_output.py"
            output.parent.mkdir(parents=True)
            output.write_text("canonical output\n")
            target = root / "packages/codex/hooks/scripts/test_output.py"
            target.parent.mkdir(parents=True)
            target.symlink_to(output)
            with self.assertRaises(ValueError):
                files.materialize(root, dry_run=False)
            self.assertFalse((root / files.SEMANTIC_TARGETS[0]).exists())
            target.unlink()
            files.materialize(root, dry_run=False)
            self.assertEqual(target.read_bytes(), output.read_bytes())
            self.assertNotEqual(target.stat().st_ino, output.stat().st_ino)

    def test_codex_collision_preflight_before_mutation(self) -> None:
        """Unmanaged collisions refuse the whole agent set before provider mutations."""
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = home / "agents"
            target.mkdir()
            (target / "wiki-writer.toml").write_text("unrelated")
            with (
                patch("scripts.installer.codex.shutil.which", return_value="codex"),
                patch("scripts.installer.codex.subprocess.run") as run,
            ):
                with self.assertRaisesRegex(ValueError, "unrelated Codex agent collision"):
                    codex.install(ROOT, home, dry_run=False)
                run.assert_not_called()
            self.assertEqual(len(list(target.iterdir())), 1)

    def test_codex_dry_run_and_independent_agent_install(self) -> None:
        """Dry-run stays read-only, while installation copies all ten agents atomically."""
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex"
            with (
                patch("scripts.installer.codex.shutil.which", return_value="codex"),
                patch("scripts.installer.codex.subprocess.run") as run,
            ):
                codex.install(ROOT, home, dry_run=True)
                self.assertFalse(home.exists())
                run.assert_not_called()
                codex.install(ROOT, home, dry_run=False)
                self.assertEqual(run.call_count, 2)
                self.assertEqual(len(list((home / "agents").glob("*.toml"))), 10)
                for target in (home / "agents").glob("*.toml"):
                    self.assertEqual(target.stat().st_mode & 0o777, 0o644)

    def test_cli_dry_run_never_writes_home_or_invokes_provider(self) -> None:
        """Exercise the actual CLI with an inert executable that must never run."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            binary = base / "codex"
            binary.write_text("#!/usr/bin/env python3\nraise SystemExit(88)\n")
            binary.chmod(0o755)
            home = base / "home"
            environment = dict(
                os.environ,
                HOME=str(home),
                CODEX_HOME=str(home / ".codex"),
                PYTHONDONTWRITEBYTECODE="1",
                PATH=str(base) + os.pathsep + os.environ.get("PATH", ""),
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "install.py"), "--provider", "codex", "--dry-run"],
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(home.exists(), str(list(home.rglob("*"))))
            self.assertIn("would: codex plugin add", result.stdout)
            invalid = subprocess.run(
                [sys.executable, str(ROOT / "install.py"), "--provider", "codex", "--memory-target", "unused"],
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(invalid.returncode, 1)
            self.assertFalse(home.exists())

    def test_uninstall_preserves_other_sections_and_data(self) -> None:
        """Remove only managed discipline and marketplace keys, retaining backups."""
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            claude = home / ".claude"
            claude.mkdir()
            document = claude / "CLAUDE.md"
            document.write_text("# Personal\n## Self-Checking Discipline\nremove\n## Other\nkeep\n")
            settings = claude / "settings.json"
            settings.write_text(json.dumps({"extraKnownMarketplaces": {"coderails": {}, "other": {}}}))
            from scripts.installer.claude import uninstall

            uninstall(home)
            self.assertEqual(document.read_text(), "# Personal\n## Other\nkeep\n")
            self.assertEqual(json.loads(settings.read_text())["extraKnownMarketplaces"], {"other": {}})
            self.assertTrue(list(claude.glob("CLAUDE.md.bak.*")))


if __name__ == "__main__":
    unittest.main()
